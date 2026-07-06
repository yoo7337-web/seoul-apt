"""집계 - 구/단지/면적별 월별 추세, 평단가·전세가율·거래량·랭킹.

SQLite 에 median 함수가 없어 그룹 값을 파이썬으로 가져와 통계 계산한다.
가격 단위는 만원. 평단가는 만원/평(전용면적 기준).
"""

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from . import config


def _dist_km(lat1, lon1, lat2, lon2) -> float:
    """두 좌표 간 거리(km, haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return r * 2 * math.asin(math.sqrt(a))


def nearby_sale_median(conn, lat, lon, exclu_area, radius_km: float = 1.5,
                       months: int = 15, area_tol: float = 0.12) -> dict | None:
    """반경 내 '비슷한 전용면적'(±area_tol) 최근 매매 중앙값(만원). 청약 안전마진용.

    분양가와 비교할 '주변 시세'. 버킷(~60㎡ 등)은 폭이 넓어 25㎡·59㎡가 섞이므로
    분양 주택형의 전용면적에 ±12% 근접한 거래만 비교한다. 표본 3건 미만이면 None.
    """
    if lat is None or lon is None or not exclu_area:
        return None
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)) or 1)
    cxs = conn.execute(
        "SELECT complex_id, lat, lon FROM complex "
        "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
    ids = [c["complex_id"] for c in cxs
           if _dist_km(lat, lon, c["lat"], c["lon"]) <= radius_km]
    if not ids:
        return None
    lo_ar, hi_ar = exclu_area * (1 - area_tol), exclu_area * (1 + area_tol)
    since = (date.today() - timedelta(days=months * 30)).isoformat()
    q = ("SELECT amount_manwon FROM sale_txn "
         "WHERE canceled=0 AND deal_date>=? AND exclu_area BETWEEN ? AND ? "
         "AND complex_id IN (%s)" % ",".join("?" * len(ids)))
    amounts = [r["amount_manwon"] for r in
               conn.execute(q, [since, lo_ar, hi_ar] + ids).fetchall()]
    if len(amounts) < 3:
        return None
    return {"median": round(_median(amounts)), "n": len(amounts)}


def _median(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def _pyeong(area_sqm: float) -> float:
    return area_sqm * config.PYEONG_PER_SQM


def _month(deal_date: str) -> str:
    return deal_date[:7]  # 'YYYY-MM'


def _by_area(rows: list, amount_key: str, since: str) -> dict:
    """전용면적 버킷별 '최근' 대표가. 거래 있는 버킷만 포함.

    각 버킷에서 since(최근 1년) 이후 거래의 중앙값(만원)과 중앙 전용면적(평)을
    산출한다. 1년 내 거래가 없으면 가장 최근 1건으로 대체하고 s(오래됨)=1 표시.
    '최근 N건'이 아닌 기간 기준이라 단지마다 '최근'의 의미가 일관된다.

    rows 는 deal_date DESC 정렬 가정(매매는 canceled=0).
    amount_key: 매매는 'amount_manwon', 전세는 'deposit_manwon'.
    반환 {버킷: {"p": 가격(만원), "py": 평, "s": 1?}}.
    """
    by_bucket: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["exclu_area"] is None:
            continue
        by_bucket[config.area_bucket(r["exclu_area"])].append(r)
    out = {}
    for b, rs in by_bucket.items():          # rs: deal_date DESC
        recent = [r for r in rs if r["deal_date"] >= since]
        use = recent or rs[:1]
        p = _median([r[amount_key] for r in use])
        if p is None:
            continue
        py = _median([_pyeong(r["exclu_area"]) for r in use])
        item = {"p": round(p), "py": round(py) if py else None}
        if not recent:
            item["s"] = 1                      # 1년 내 거래 없음(가격 오래됨)
        out[b] = item
    return out


# 단지 대표 평형 동률 시 우선순위(국민평형대 우선)
_REP_PRIORITY = {"60~85㎡": 0, "85~135㎡": 1, "~60㎡": 2, "135㎡~": 3}


def _rep_bucket(rows: list) -> str | None:
    """단지 대표 평형 - 전체 거래에서 가장 많이 거래된 전용면적 버킷.

    지도에서 '전체 평형'일 때 이 대표 평형의 최근가를 말풍선에 표시한다
    (전 면적 혼합 중앙값 대신). 동률이면 국민평형대(60~85㎡)를 우선한다.
    """
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["exclu_area"] is not None:
            counts[config.area_bucket(r["exclu_area"])] += 1
    if not counts:
        return None
    return max(counts, key=lambda b: (counts[b], -_REP_PRIORITY.get(b, 9)))


def representative_months(monthly: list[dict]) -> list[dict]:
    """대표값 산정용 월 목록 - 평단가가 있고 표본이 충분한 월만.

    현재 진행 중인 부분월(예: 이달 초, 거래 1~2건)이 대표 평단가·랭킹을
    왜곡하지 않도록 MIN_MONTH_SAMPLE 미만 월을 제외한다. 충분한 월이 하나도
    없으면(수집 초기) 표본 기준을 버리고 평단가 있는 월로 대체한다.
    """
    ok = [m for m in monthly
          if m["ppy_median"] and m["sale_count"] >= config.MIN_MONTH_SAMPLE]
    if ok:
        return ok
    return [m for m in monthly if m["ppy_median"]]


# ── 구 단위 월별 추세 ────────────────────────────────────────────────────
def district_monthly(conn, lawd_cd: str) -> list[dict]:
    """구의 월별 매매/전세/월세 중앙값·건수·평단가."""
    sales = conn.execute(
        "SELECT s.deal_date, s.exclu_area, s.amount_manwon "
        "FROM sale_txn s JOIN complex c ON s.complex_id=c.complex_id "
        "WHERE c.lawd_cd=? AND s.canceled=0", (lawd_cd,)).fetchall()
    rents = conn.execute(
        "SELECT r.deal_date, r.deposit_manwon, r.monthly_manwon, r.rent_type "
        "FROM rent_txn r JOIN complex c ON r.complex_id=c.complex_id "
        "WHERE c.lawd_cd=?", (lawd_cd,)).fetchall()

    sale_by_m = defaultdict(list)      # month -> [amount]
    ppy_by_m = defaultdict(list)       # month -> [평단가]
    for s in sales:
        m = _month(s["deal_date"])
        sale_by_m[m].append(s["amount_manwon"])
        py = _pyeong(s["exclu_area"])
        if py > 0:
            ppy_by_m[m].append(s["amount_manwon"] / py)

    jeonse_by_m = defaultdict(list)
    wolse_by_m = defaultdict(list)
    for r in rents:
        m = _month(r["deal_date"])
        if r["rent_type"] == "jeonse":
            jeonse_by_m[m].append(r["deposit_manwon"])
        else:
            wolse_by_m[m].append(r["monthly_manwon"])

    months = sorted(set(sale_by_m) | set(jeonse_by_m) | set(wolse_by_m))
    out = []
    for m in months:
        sale_med = _median(sale_by_m.get(m, []))
        jeonse_med = _median(jeonse_by_m.get(m, []))
        out.append({
            "month": m,
            "sale_median": sale_med,
            "sale_count": len(sale_by_m.get(m, [])),
            "ppy_median": _median(ppy_by_m.get(m, [])),  # 만원/평
            "jeonse_median": jeonse_med,
            "jeonse_count": len(jeonse_by_m.get(m, [])),
            "wolse_median": _median(wolse_by_m.get(m, [])),
            "wolse_count": len(wolse_by_m.get(m, [])),
            "jeonse_ratio": round(jeonse_med / sale_med * 100, 1)
            if sale_med and jeonse_med else None,
        })
    return out


def district_recent_txns(conn, lawd_cd: str, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT s.deal_date, c.apt_nm, s.exclu_area, s.floor, s.amount_manwon "
        "FROM sale_txn s JOIN complex c ON s.complex_id=c.complex_id "
        "WHERE c.lawd_cd=? AND s.canceled=0 "
        "ORDER BY s.deal_date DESC, s.id DESC LIMIT ?",
        (lawd_cd, limit)).fetchall()
    return [{
        "date": r["deal_date"], "apt": r["apt_nm"], "area": r["exclu_area"],
        "floor": r["floor"], "amount": r["amount_manwon"],
        "ppy": round(r["amount_manwon"] / _pyeong(r["exclu_area"]), 0)
        if r["exclu_area"] else None,
    } for r in rows]


# ── 단지 단위 ────────────────────────────────────────────────────────────
def complex_list(conn, lawd_cd: str) -> list[dict]:
    """구의 단지 목록 - 좌표·대표가·평단가·전세가율·공시가격."""
    complexes = conn.execute(
        "SELECT * FROM complex WHERE lawd_cd=?", (lawd_cd,)).fetchall()
    year_ago = (date.today() - timedelta(days=365)).isoformat()
    out = []
    for c in complexes:
        cid = c["complex_id"]
        sale_rows = conn.execute(
            "SELECT deal_date, exclu_area, amount_manwon FROM sale_txn "
            "WHERE complex_id=? AND canceled=0 "
            "ORDER BY deal_date DESC", (cid,)).fetchall()
        if not sale_rows:
            recent_sales = []
        else:
            recent_sales = sale_rows
        # 최근 1년 매매 중앙값 및 평단가
        recent = recent_sales[:50]
        sale_med = _median([r["amount_manwon"] for r in recent])
        ppy = _median([r["amount_manwon"] / _pyeong(r["exclu_area"])
                       for r in recent if r["exclu_area"]])
        # 평형(전용면적 버킷)별 최근 대표가 - 지도 평형 선택 시 사용
        sale_by_area = _by_area(recent_sales, "amount_manwon", year_ago)
        rep = _rep_bucket(recent_sales)       # 대표 평형(전체 평형 표시용)
        # 단지 전용면적 범위(㎡) - 슬라이더 평형 필터용
        areas = [r["exclu_area"] for r in recent_sales if r["exclu_area"]]
        area_min = round(min(areas), 1) if areas else None
        area_max = round(max(areas), 1) if areas else None
        # 역대 최고가(신고가 하이라이트용)
        peak = max((r["amount_manwon"] for r in recent_sales), default=None)
        last_amount = recent_sales[0]["amount_manwon"] if recent_sales else None
        # 최근 1년 거래 건수(활발도 필터) + 고점대비 하락률(%)
        # 고점대비는 '최근 1건 거래' 기준 → 신고가(is_peak)면 0%가 되어 하락 필터에서 제외
        n1y = sum(1 for r in recent_sales if r["deal_date"] >= year_ago)
        drop_pct = (round((last_amount - peak) / peak * 100, 1)
                    if peak and last_amount else None)

        jeonse_rows = conn.execute(
            "SELECT deal_date, exclu_area, deposit_manwon FROM rent_txn "
            "WHERE complex_id=? AND rent_type='jeonse' "
            "ORDER BY deal_date DESC", (cid,)).fetchall()
        jeonse_med = _median([r["deposit_manwon"] for r in jeonse_rows[:30]])
        jeonse_by_area = _by_area(jeonse_rows, "deposit_manwon", year_ago)
        jrep = _rep_bucket(jeonse_rows)       # 전세 대표 평형

        gongsi = conn.execute(
            "SELECT year, price_manwon FROM gongsi_price "
            "WHERE complex_id=? ORDER BY year DESC LIMIT 1", (cid,)).fetchone()

        out.append({
            "id": cid,
            "apt": c["apt_nm"],
            "umd": c["umd_nm"],
            "build_year": c["build_year"],
            "lat": c["lat"],
            "lon": c["lon"],
            "sale_median": sale_med,
            "sale_by_area": sale_by_area,
            "rep": rep,
            "area_min": area_min,
            "area_max": area_max,
            "ppy_median": round(ppy, 0) if ppy else None,
            "sale_count": len(recent_sales),
            "sale_1y": n1y,
            "drop_pct": drop_pct,
            "households": c["households"],
            "far": c["far"],
            "last_amount": last_amount,
            "peak_amount": peak,
            "is_peak": bool(last_amount and peak and last_amount >= peak),
            "jeonse_median": jeonse_med,
            "jeonse_by_area": jeonse_by_area,
            "jrep": jrep,
            "jeonse_ratio": round(jeonse_med / sale_med * 100, 1)
            if jeonse_med and sale_med else None,
            "gongsi_price": gongsi["price_manwon"] if gongsi else None,
            "gongsi_year": gongsi["year"] if gongsi else None,
            "gongsi_ratio": round(gongsi["price_manwon"] / sale_med * 100, 1)
            if gongsi and sale_med else None,
        })
    return out


def _valuation(ppy_series: list, jr_series: list) -> dict | None:
    """장기 평단가·전세가율 상 '현재 위치'. 지금 싼가 비싼가를 한눈에.

    ppy_series: [{"m": 'YYYY-MM', "v": 만원/평}], jr_series: [{"y": 'YYYY', "v": %}].
    - pos: 최근 5년 범위에서 현재가 위치(0=5년저점, 100=5년고점)
    - vs_peak: 역대 최고 평단가 대비 현재(%)
    - jr_pct: 현재 전세가율의 역대 백분위(높을수록 하방 견고 신호)
    표본이 12개월 미만이면 None(판단 유보).
    """
    if len(ppy_series) < 12:
        return None
    vals = [p["v"] for p in ppy_series]
    cur = _median([p["v"] for p in ppy_series[-3:]])   # 최근 3개월로 안정화
    peak = max(vals)
    recent = vals[-60:]                                # 최근 5년(60개월)
    lo, hi = min(recent), max(recent)
    out = {
        "cur_ppy": round(cur), "lo5": round(lo), "hi5": round(hi),
        "pos": round((cur - lo) / (hi - lo) * 100) if hi > lo else 50,
        "peak": round(peak),
        "vs_peak": round((cur - peak) / peak * 100, 1) if peak else None,
        "months": len(ppy_series),
    }
    if jr_series:
        jrs = [j["v"] for j in jr_series]
        cur_jr = jr_series[-1]["v"]
        out.update({
            "jr_cur": cur_jr, "jr_lo": min(jrs), "jr_hi": max(jrs),
            "jr_pct": round(sum(1 for x in jrs if x <= cur_jr) / len(jrs) * 100),
        })
    return out


def complex_detail(conn, complex_id: int) -> dict:
    """단지의 면적버킷별 월별 매매/전세/월세 추세 + 최근 거래 + 밸류에이션."""
    sales = conn.execute(
        "SELECT deal_date, exclu_area, floor, amount_manwon, canceled "
        "FROM sale_txn WHERE complex_id=? ORDER BY deal_date",
        (complex_id,)).fetchall()
    rents = conn.execute(
        "SELECT deal_date, exclu_area, floor, deposit_manwon, monthly_manwon, "
        "rent_type FROM rent_txn WHERE complex_id=? ORDER BY deal_date",
        (complex_id,)).fetchall()

    # 면적버킷 -> month -> 값들
    sale_series = defaultdict(lambda: defaultdict(list))
    jeonse_series = defaultdict(lambda: defaultdict(list))
    for s in sales:
        if s["canceled"]:
            continue  # 해제 거래는 시세 추세에서 제외
        b = config.area_bucket(s["exclu_area"])
        sale_series[b][_month(s["deal_date"])].append(s["amount_manwon"])
    for r in rents:
        if r["rent_type"] != "jeonse":
            continue
        b = config.area_bucket(r["exclu_area"])
        jeonse_series[b][_month(r["deal_date"])].append(r["deposit_manwon"])

    def _series(store):
        result = {}
        for bucket, by_m in store.items():
            result[bucket] = [
                {"month": m, "median": _median(v), "count": len(v)}
                for m, v in sorted(by_m.items())
            ]
        return result

    # 최근 거래에는 해제 건도 플래그와 함께 노출(프런트에서 취소선 표시)
    recent = [{
        "date": s["deal_date"], "area": s["exclu_area"], "floor": s["floor"],
        "amount": s["amount_manwon"], "canceled": int(s["canceled"] or 0),
    } for s in sorted(sales, key=lambda x: x["deal_date"], reverse=True)[:40]]

    # 최근 전월세 실거래(전세=월세 0). type 으로 구분해 프런트에서 표기.
    recent_rents = [{
        "date": r["deal_date"], "area": r["exclu_area"], "floor": r["floor"],
        "deposit": r["deposit_manwon"], "monthly": r["monthly_manwon"],
        "type": r["rent_type"],
    } for r in sorted(rents, key=lambda x: x["deal_date"], reverse=True)[:40]]

    # ── 밸류에이션용 시계열(전 면적 평단가 월별 + 전세가율 연도별) ──
    ppy_by_m = defaultdict(list)
    sale_ppy_by_y = defaultdict(list)
    for s in sales:
        if s["canceled"]:
            continue
        py = _pyeong(s["exclu_area"])
        if py > 0:
            ppy_by_m[_month(s["deal_date"])].append(s["amount_manwon"] / py)
            sale_ppy_by_y[s["deal_date"][:4]].append(s["amount_manwon"] / py)
    ppy_series = [{"m": m, "v": round(_median(v))}
                  for m, v in sorted(ppy_by_m.items())]
    jeonse_ppy_by_y = defaultdict(list)
    for r in rents:
        if r["rent_type"] != "jeonse":
            continue
        py = _pyeong(r["exclu_area"])
        if py > 0:
            jeonse_ppy_by_y[r["deal_date"][:4]].append(r["deposit_manwon"] / py)
    jr_series = []
    for y in sorted(sale_ppy_by_y):
        sp, jp = _median(sale_ppy_by_y[y]), _median(jeonse_ppy_by_y.get(y, []))
        if sp and jp:
            jr_series.append({"y": y, "v": round(jp / sp * 100, 1)})

    gongsi = conn.execute(
        "SELECT year, exclu_area, price_manwon FROM gongsi_price "
        "WHERE complex_id=? ORDER BY year DESC", (complex_id,)).fetchall()

    meta = conn.execute(
        "SELECT build_year, umd_nm, households, far, bcr, approval_date "
        "FROM complex WHERE complex_id=?", (complex_id,)).fetchone()

    return {
        "build_year": meta["build_year"] if meta else None,
        "umd": meta["umd_nm"] if meta else None,
        "households": meta["households"] if meta else None,
        "far": meta["far"] if meta else None,
        "bcr": meta["bcr"] if meta else None,
        "approval_date": meta["approval_date"] if meta else None,
        "sale_series": _series(sale_series),
        "jeonse_series": _series(jeonse_series),
        "valuation": _valuation(ppy_series, jr_series),
        "ppy_series": ppy_series,          # 장기 평단가 스파크라인용(만원/평)
        "recent_sales": recent,
        "recent_rents": recent_rents,
        "gongsi": [{"year": g["year"], "area": g["exclu_area"],
                    "price": g["price_manwon"]} for g in gongsi],
    }


def district_peak_share(conn, days: int = 90) -> list[dict]:
    """구별 최근 N일 매매 중 신고가(단지 역대 최고가) 거래 비중(%).

    어느 지역이 최근에 고점을 갱신하며 오르는지 보는 모멘텀 지표.
    기준일은 DB 최신 계약일(수집 지연 무관). 표본 노이즈를 줄이기 위해
    누적 거래 3건 미만 단지의 거래는 신고가로 치지 않는다.
    """
    anchor = conn.execute(
        "SELECT MAX(deal_date) AS d FROM sale_txn WHERE canceled=0").fetchone()["d"]
    if not anchor:
        return []
    y, m, d = (int(x) for x in anchor.split("-"))
    cutoff = (date(y, m, d) - timedelta(days=days)).isoformat()

    rows = conn.execute(
        """SELECT c.lawd_cd,
                  COUNT(*) AS total,
                  SUM(CASE WHEN s.amount_manwon >= cm.mx AND cm.n >= 3
                      THEN 1 ELSE 0 END) AS peaks
           FROM sale_txn s
           JOIN complex c ON s.complex_id = c.complex_id
           JOIN (SELECT complex_id, MAX(amount_manwon) AS mx, COUNT(*) AS n
                 FROM sale_txn WHERE canceled=0 GROUP BY complex_id) cm
             ON cm.complex_id = s.complex_id
           WHERE s.canceled=0 AND s.deal_date >= ?
           GROUP BY c.lawd_cd""", (cutoff,)).fetchall()

    out = []
    for r in rows:
        total, peaks = r["total"], r["peaks"] or 0
        out.append({
            "lawd_cd": r["lawd_cd"],
            "name": config.SEOUL_DISTRICTS.get(r["lawd_cd"], r["lawd_cd"]),
            "total": total,
            "peaks": peaks,
            "share": round(peaks / total * 100, 1) if total else 0.0,
        })
    out.sort(key=lambda x: -x["share"])
    return out


# ── 랭킹 / 부동산원 ──────────────────────────────────────────────────────
def _phase(vol_ratio, price_chg) -> str:
    """거래량 모멘텀 × 가격 모멘텀 → 부동산 시계 4국면.
    거래량↑가격↑=과열 / 거래량↑가격↓=회복 / 거래량↓가격↑=둔화 / 거래량↓가격↓=침체.
    경계(혼조)는 중립."""
    if vol_ratio is None or price_chg is None:
        return "neutral"
    vol = 1 if vol_ratio >= 1.05 else (-1 if vol_ratio <= 0.95 else 0)
    prc = 1 if price_chg >= 0.5 else (-1 if price_chg <= -0.5 else 0)
    if vol > 0 and prc > 0:
        return "boom"        # 과열(상승)
    if vol > 0 and prc < 0:
        return "recovery"    # 회복(거래 먼저 살아남)
    if vol < 0 and prc > 0:
        return "slowdown"    # 둔화(가격 관성, 거래 위축)
    if vol < 0 and prc < 0:
        return "recession"   # 침체
    return "neutral"


def market_phase(conn) -> list[dict]:
    """구별 시장 국면 - 거래량 모멘텀(최근3개월/직전12개월 월평균)과
    가격 6개월 변화율로 4국면 판정. 불완전 당월은 제외해 왜곡을 줄인다."""
    ranks = {r["lawd_cd"]: r for r in district_rankings(conn)}
    out = []
    for lawd_cd, name in config.SEOUL_DISTRICTS.items():
        monthly = district_monthly(conn, lawd_cd)   # 월 오름차순
        counts = [m["sale_count"] for m in monthly]
        if len(counts) < 16:
            continue
        recent = counts[-4:-1]          # 최근 3개월(당월 제외)
        base = counts[-16:-4]           # 직전 12개월
        base_avg = sum(base) / len(base) if base else 0
        vol_ratio = round((sum(recent) / len(recent)) / base_avg, 2) \
            if base_avg else None
        price_chg = ranks.get(lawd_cd, {}).get("change_6m")
        out.append({
            "lawd_cd": lawd_cd, "name": name,
            "vol_ratio": vol_ratio, "price_chg": price_chg,
            "phase": _phase(vol_ratio, price_chg),
        })
    return out


def recent_bargains(conn, days: int = 45, threshold: float = -7.0,
                    min_sample: int = 5, area_tol: float = 0.12,
                    low_floor: int = 2, min_disc: float = -40.0,
                    limit: int = 60) -> list[dict]:
    """최근 N일 매매 중 '급매' - 동일 단지·비슷한 전용면적(±area_tol) 최근 1년
    중앙값 대비 threshold%(기본 -7%) 이하. 저층(≤low_floor)은 제외.
    -40% 미만(min_disc)은 지분·증여성 등 비정상 거래일 가능성이 커 제외한다.
    notify.bargain_deals 와 같은 판정을 '기간 기준'으로 모아 대시보드에 노출한다.
    기준일은 DB 최신 계약일(수집 지연 무관)."""
    anchor = conn.execute(
        "SELECT MAX(deal_date) AS d FROM sale_txn WHERE canceled=0").fetchone()["d"]
    if not anchor:
        return []
    y, m, d = (int(x) for x in anchor.split("-"))
    win = (date(y, m, d) - timedelta(days=days)).isoformat()
    since1y = (date(y, m, d) - timedelta(days=365)).isoformat()
    rows = conn.execute(
        """SELECT s.id, s.deal_date, s.exclu_area, s.floor, s.amount_manwon,
                  s.complex_id, c.lawd_cd, c.umd_nm, c.apt_nm
           FROM sale_txn s JOIN complex c ON s.complex_id=c.complex_id
           WHERE s.canceled=0 AND s.deal_date>=? ORDER BY s.deal_date DESC""",
        (win,)).fetchall()
    out = []
    for r in rows:
        if r["floor"] and r["floor"] <= low_floor:
            continue
        area = r["exclu_area"]
        lo, hi = area * (1 - area_tol), area * (1 + area_tol)
        amts = [x["amount_manwon"] for x in conn.execute(
            "SELECT amount_manwon FROM sale_txn WHERE complex_id=? AND canceled=0 "
            "AND id!=? AND deal_date>=? AND exclu_area BETWEEN ? AND ?",
            (r["complex_id"], r["id"], since1y, lo, hi))]
        if len(amts) < min_sample:
            continue
        med = _median(amts)
        if not med:
            continue
        disc = round((r["amount_manwon"] - med) / med * 100, 1)
        if disc <= threshold and disc >= min_disc:   # 급매지만 비정상 극단은 제외
            out.append({
                "id": r["complex_id"], "apt": r["apt_nm"], "lawd_cd": r["lawd_cd"],
                "umd": r["umd_nm"], "area": r["exclu_area"], "floor": r["floor"],
                "amount": r["amount_manwon"], "med": round(med), "disc": disc,
                "date": r["deal_date"],
            })
    out.sort(key=lambda x: x["disc"])   # 할인폭 큰 순
    return out[:limit]


def district_rankings(conn) -> list[dict]:
    """구별 평단가 중앙값과 최근 6개월 상승률 랭킹."""
    out = []
    for lawd_cd, name in config.SEOUL_DISTRICTS.items():
        monthly = district_monthly(conn, lawd_cd)
        ppy_months = representative_months(monthly)
        if not ppy_months:
            continue
        latest = ppy_months[-1]["ppy_median"]
        prev = ppy_months[-7]["ppy_median"] if len(ppy_months) >= 7 else \
            ppy_months[0]["ppy_median"]
        change = round((latest - prev) / prev * 100, 1) if prev else None
        out.append({
            "lawd_cd": lawd_cd, "name": name,
            "ppy_median": latest, "change_6m": change,
            "sale_count": sum(m["sale_count"] for m in monthly),
        })
    out.sort(key=lambda x: x["ppy_median"] or 0, reverse=True)
    return out


def reb_series(conn) -> dict:
    """부동산원 지수를 지표별 서울 시계열로 정리."""
    rows = conn.execute(
        "SELECT region, stat_name, period, value FROM reb_index "
        "ORDER BY period").fetchall()
    series = defaultdict(lambda: defaultdict(list))
    for r in rows:
        series[r["stat_name"]][r["region"]].append(
            {"period": r["period"], "value": r["value"]})
    return {stat: dict(regions) for stat, regions in series.items()}
