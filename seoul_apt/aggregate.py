"""집계 - 구/단지/면적별 월별 추세, 평단가·전세가율·거래량·랭킹.

SQLite 에 median 함수가 없어 그룹 값을 파이썬으로 가져와 통계 계산한다.
가격 단위는 만원. 평단가는 만원/평(전용면적 기준).
"""

import statistics
from collections import defaultdict

from . import config


def _median(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def _pyeong(area_sqm: float) -> float:
    return area_sqm * config.PYEONG_PER_SQM


def _month(deal_date: str) -> str:
    return deal_date[:7]  # 'YYYY-MM'


# 지도 평형별 대표가 산출 시 버킷당 사용할 최근 거래 수
AREA_MARKER_RECENT = 30


def _sale_by_area(sale_rows: list) -> dict:
    """전용면적 버킷별 최근 거래 중앙값(만원). 거래 있는 버킷만 포함.

    sale_rows 는 canceled=0, deal_date DESC 로 정렬돼 있다고 가정.
    각 버킷의 최근 AREA_MARKER_RECENT 건만 취해 중앙값을 낸다.
    """
    by_bucket: dict[str, list] = defaultdict(list)
    for r in sale_rows:
        if r["exclu_area"] is None:
            continue
        b = config.area_bucket(r["exclu_area"])
        if len(by_bucket[b]) < AREA_MARKER_RECENT:
            by_bucket[b].append(r["amount_manwon"])
    out = {}
    for b, amounts in by_bucket.items():
        m = _median(amounts)
        if m is not None:
            out[b] = m
    return out


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
        # 평형(전용면적 버킷)별 최근 거래 중앙값 - 지도에서 평형 선택 시 사용
        sale_by_area = _sale_by_area(recent_sales)
        # 역대 최고가(신고가 하이라이트용)
        peak = max((r["amount_manwon"] for r in recent_sales), default=None)
        last_amount = recent_sales[0]["amount_manwon"] if recent_sales else None

        jeonse_rows = conn.execute(
            "SELECT deposit_manwon FROM rent_txn "
            "WHERE complex_id=? AND rent_type='jeonse' "
            "ORDER BY deal_date DESC LIMIT 30", (cid,)).fetchall()
        jeonse_med = _median([r["deposit_manwon"] for r in jeonse_rows])

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
            "ppy_median": round(ppy, 0) if ppy else None,
            "sale_count": len(recent_sales),
            "last_amount": last_amount,
            "peak_amount": peak,
            "is_peak": bool(last_amount and peak and last_amount >= peak),
            "jeonse_median": jeonse_med,
            "jeonse_ratio": round(jeonse_med / sale_med * 100, 1)
            if jeonse_med and sale_med else None,
            "gongsi_price": gongsi["price_manwon"] if gongsi else None,
            "gongsi_year": gongsi["year"] if gongsi else None,
            "gongsi_ratio": round(gongsi["price_manwon"] / sale_med * 100, 1)
            if gongsi and sale_med else None,
        })
    return out


def complex_detail(conn, complex_id: int) -> dict:
    """단지의 면적버킷별 월별 매매/전세/월세 추세 + 최근 거래."""
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

    gongsi = conn.execute(
        "SELECT year, exclu_area, price_manwon FROM gongsi_price "
        "WHERE complex_id=? ORDER BY year DESC", (complex_id,)).fetchall()

    meta = conn.execute(
        "SELECT build_year, umd_nm FROM complex WHERE complex_id=?",
        (complex_id,)).fetchone()

    return {
        "build_year": meta["build_year"] if meta else None,
        "umd": meta["umd_nm"] if meta else None,
        "sale_series": _series(sale_series),
        "jeonse_series": _series(jeonse_series),
        "recent_sales": recent,
        "recent_rents": recent_rents,
        "gongsi": [{"year": g["year"], "area": g["exclu_area"],
                    "price": g["price_manwon"]} for g in gongsi],
    }


# ── 랭킹 / 부동산원 ──────────────────────────────────────────────────────
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
