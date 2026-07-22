"""SQLite → 정적 사이트(docs/data)용 JSON 내보내기.

산출물:
  meta.json                     전체 메타(기준일·구목록·합계)
  markers.json                  지도 마커용 경량 단지 좌표+대표가
  districts/<lawd_cd>.json      구 요약·월별추세·최근거래·단지목록
  complex/<lawd_cd>/<id>.json   단지 면적별 월별 추세(지연 로드)
  reb/seoul_index.json          부동산원 지수 시계열
docs/js/config.js 에 KAKAO_JS_KEY 를 주입한다(없으면 빈 값).
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import config, aggregate
from .subscription import extract_gu

_TY_AREA = re.compile(r"[\d.]+")


def _ty_exclu_area(house_ty: str) -> float | None:
    """주택형(예: '084.9700A')의 앞부분 전용면적(㎡) 추출."""
    m = _TY_AREA.match((house_ty or "").strip())
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None

KST = timezone(timedelta(hours=9))


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def export_all(conn, kakao_js_key: str | None = None) -> dict:
    now = datetime.now(KST)
    export_dir = config.EXPORT_DIR
    markers = []
    district_list = []
    ppy_trend = {}   # 대시보드용: 구별 월별 평단가(경량)
    val_items = []   # 밸류에이션 종합(대시보드 밸류에이션 섹션용)
    totals = {"sale": 0, "rent": 0, "complex": 0}
    listing_summary = _listing_summary(conn)   # {complex_id: {ns, nj, minp}}

    for lawd_cd, name in config.SEOUL_DISTRICTS.items():
        monthly = aggregate.district_monthly(conn, lawd_cd)
        ppy_trend[lawd_cd] = [
            {"m": m["month"], "p": m["ppy_median"]}
            for m in monthly if m["ppy_median"]
        ]
        complexes = aggregate.complex_list(conn, lawd_cd)
        recent = aggregate.district_recent_txns(conn, lawd_cd, limit=30)

        sale_count = sum(m["sale_count"] for m in monthly)
        rent_count = sum(m["jeonse_count"] + m["wolse_count"] for m in monthly)
        totals["sale"] += sale_count
        totals["rent"] += rent_count
        totals["complex"] += len(complexes)

        rep_months = aggregate.representative_months(monthly)
        latest = rep_months[-1] if rep_months else {}
        district_list.append({
            "lawd_cd": lawd_cd, "name": name,
            "sale_count": sale_count,
            "complex_count": len(complexes),
            "ppy_median": latest.get("ppy_median"),
            "sale_median": latest.get("sale_median"),
        })

        _write_json(export_dir / "districts" / f"{lawd_cd}.json", {
            "lawd_cd": lawd_cd, "name": name,
            "monthly": monthly,
            "recent_txns": recent,
            "complexes": complexes,
        })

        # 단지 상세(지연 로드용)
        for c in complexes:
            detail = aggregate.complex_detail(conn, c["id"])
            detail["id"] = c["id"]
            detail["apt"] = c["apt"]
            detail["lawd_cd"] = lawd_cd
            _write_json(export_dir / "complex" / lawd_cd / f"{c['id']}.json", detail)
            v = detail.get("valuation")
            if v and c["lat"] and c["lon"]:
                va = detail.get("valuation_area") or {}
                val_items.append({
                    "id": c["id"], "apt": c["apt"], "lawd": lawd_cd,
                    "all": _val_short(v),
                    "areas": {b: _val_short(x) for b, x in va.items()},
                })
            if c["lat"] and c["lon"]:
                markers.append({
                    "id": c["id"], "lawd_cd": lawd_cd, "apt": c["apt"],
                    "lat": c["lat"], "lon": c["lon"],
                    "ppy": c["ppy_median"], "sale": c["sale_median"],
                    "sale_area": c["sale_by_area"],
                    "rep": c["rep"],             # 매매 대표 평형(전체 표시용)
                    "jeonse": c["jeonse_median"],
                    "jeonse_area": c["jeonse_by_area"],
                    "jrep": c["jrep"],           # 전세 대표 평형
                    "jeonse_ratio": c["jeonse_ratio"],
                    "is_peak": c["is_peak"],
                    # 필터용 부가 필드(짧은 키로 용량 절약)
                    "by": c["build_year"],       # 준공연도
                    "hh": c["households"],       # 세대수
                    "far": c["far"],             # 용적률(%)
                    "n1y": c["sale_1y"],         # 최근 1년 매매 건수
                    "drop": c["drop_pct"],       # 고점대비 %(음수=하락)
                    "am": c["area_min"],         # 전용면적 최소(㎡)
                    "ax": c["area_max"],         # 전용면적 최대(㎡)
                    "sw": c["subway_m"],         # 최근접 지하철역 거리(m)
                    "swn": c["subway_nm"],       # 최근접 역명(+노선)
                    "el": c["school_m"],         # 최근접 초등학교 거리(m)
                    **_marker_listing(listing_summary.get(c["id"])),
                })

    _write_json(export_dir / "markers.json", {"markers": markers})
    _write_json(export_dir / "reb" / "seoul_index.json",
                aggregate.reb_series(conn))
    # 현재 매물(호가) — 단지별 그룹. 별도 파일 지연 로드(마커 용량 보호).
    _write_json(export_dir / "listings.json", listings_payload(conn, now))
    # 청약·분양(진행중 + 최근 1년 마감분)
    _write_json(export_dir / "subscription.json", {
        "generated": now.isoformat(timespec="seconds"),
        "items": subscription_items(conn, now.date().isoformat()),
    })
    # 밸류에이션 종합(구별 히트맵·저평가 리스트·산점도용). 평형 버킷별 값 포함.
    # 구별 요약은 프런트에서 선택 평형에 따라 계산한다.
    _write_json(export_dir / "valuation.json", {
        "generated": now.isoformat(timespec="seconds"),
        "items": val_items,
    })
    # 대시보드 전용 데이터(구별 평단가 추이 + 신고가 비중)
    _write_json(export_dir / "dashboard.json", {
        "generated": now.isoformat(timespec="seconds"),
        "ppy_trend": ppy_trend,
        "peak_share": aggregate.district_peak_share(conn, days=90),
        "peak_share_days": 90,
        "market_phase": aggregate.market_phase(conn),
        "bargains": aggregate.recent_bargains(conn, days=45),
        "bargains_days": 45,
    })
    _write_json(export_dir / "meta.json", {
        "last_updated": now.isoformat(timespec="seconds"),
        "last_updated_display": now.strftime("%Y-%m-%d %H:%M KST"),
        "sources": data_sources(conn),   # 데이터 소스별 실제 기준일자
        "districts": district_list,
        "rankings": aggregate.district_rankings(conn),
        "totals": totals,
        "marker_count": len(markers),
    })

    _write_config_js(kakao_js_key)
    return {"markers": len(markers), **totals}


def _val_short(v: dict) -> dict:
    """밸류에이션 객체를 밸류에이션.json 용 경량 키로 축약."""
    return {"pos": v["pos"], "vp": v["vs_peak"], "jr": v["jr"],
            "ppy": v["cur_ppy"], "m": v["months"]}


def data_sources(conn) -> list[dict]:
    """데이터 소스별 실제 기준일자 - 화면 '데이터 기준일'에 표시.

    소스마다 기준이 다르다: 실거래=최신 계약일, 부동산원=발표 월(월간),
    청약=수집시각, 건축물대장=수집 진척률, 매물=최신 확인일.
    """
    def one(q):
        r = conn.execute(q).fetchone()
        return r[0] if r else None

    sale_max = one("SELECT MAX(deal_date) FROM sale_txn WHERE canceled=0")
    rent_max = one("SELECT MAX(deal_date) FROM rent_txn")
    reb_max = one("SELECT MAX(period) FROM reb_index")
    sub_max = one("SELECT MAX(rcrit_de) FROM subscription")
    bldg_done = one("SELECT COUNT(*) FROM complex WHERE bldg_fetched_at IS NOT NULL") or 0
    bldg_tot = one("SELECT COUNT(*) FROM complex") or 0
    lst_max = one("SELECT MAX(confirm_date) FROM listing WHERE status='open'")
    lst_cnt = one("SELECT COUNT(*) FROM listing WHERE status='open'") or 0
    return [
        {"k": "실거래가(매매·전월세)", "d": sale_max or "-",
         "note": f"국토부 · 최신 계약일 (전월세 {rent_max or '-'})"},
        {"k": "시장지표(가격·수급·외지인·미분양)", "d": reb_max or "-",
         "note": "한국부동산원 · 월간 발표"},
        {"k": "청약·분양", "d": sub_max or "-",
         "note": "청약홈 · 최신 모집공고일"},
        {"k": "건축물대장(세대수·용적률)", "d": f"{bldg_done:,}/{bldg_tot:,} 단지",
         "note": "건축HUB · 순차 수집 중"},
        {"k": "현재 매물(호가)", "d": lst_max or "미수집",
         "note": f"네이버부동산 · 수동 수집 {lst_cnt:,}건 (일부 구)"},
    ]


def _listing_summary(conn) -> dict:
    """단지별 open 매물 요약: {complex_id: {ns(매매수), nj(전세수), minp(최저매매호가)}}."""
    out = {}
    for r in conn.execute(
        "SELECT complex_id, trade_type, COUNT(*) n, MIN(price_manwon) minp "
        "FROM listing WHERE status='open' GROUP BY complex_id, trade_type"):
        d = out.setdefault(r["complex_id"], {"ns": 0, "nj": 0, "minp": None})
        if r["trade_type"] == "sale":
            d["ns"] = r["n"]
            d["minp"] = r["minp"]
        elif r["trade_type"] == "jeonse":
            d["nj"] = r["n"]
    return out


def _marker_listing(summ: dict | None) -> dict:
    """마커에 얹을 매물 요약(있을 때만 키 추가 - 용량 절약)."""
    if not summ:
        return {}
    out = {}
    if summ.get("ns"):
        out["ls"] = summ["ns"]      # 매매 매물수
    if summ.get("nj"):
        out["lj"] = summ["nj"]      # 전세 매물수
    return out


def listings_payload(conn, now) -> dict:
    """현재 open 매물을 단지별 그룹으로. 매매만 호가 괴리(prem) 계산.

    구조: {generated, complexes: {complex_id: {no(naver_no), at(수집시각),
      sale: [{p, mo, py, fl, ft, dong, dir, prem, d(확인일), url}...], jeonse: [...]}}}
    """
    from . import listings as L
    rows = conn.execute(
        "SELECT l.*, c.naver_no FROM listing l JOIN complex c "
        "ON c.complex_id=l.complex_id WHERE l.status='open' "
        "ORDER BY l.trade_type, l.price_manwon").fetchall()
    out = {}
    for r in rows:
        cid = r["complex_id"]
        grp = out.setdefault(str(cid), {"no": r["naver_no"], "at": None,
                                        "sale": [], "jeonse": [], "wolse": []})
        py = round(r["area_m2"] * config.PYEONG_PER_SQM) if r["area_m2"] else None
        prem = None
        if r["trade_type"] == "sale":
            prem = L.asking_premium(conn, cid, r["area_m2"], r["price_manwon"], "sale")
        item = {"p": r["price_manwon"], "py": py, "fl": r["floor"],
                "ft": r["floor_total"], "dong": r["dong"], "dir": r["direction"],
                "d": r["confirm_date"], "url": r["url"]}
        if r["area_m2"]:
            item["b"] = config.area_bucket(r["area_m2"])   # 평형 버킷(프런트 필터용)
        if r["monthly_manwon"]:
            item["mo"] = r["monthly_manwon"]
        if prem is not None:
            item["prem"] = prem
        bucket = r["trade_type"] if r["trade_type"] in grp else "sale"
        grp[bucket].append(item)
        # 수집시각은 가장 최근 last_seen
        if grp["at"] is None or (r["last_seen"] and r["last_seen"] > grp["at"]):
            grp["at"] = r["last_seen"]
    return {"generated": now.isoformat(timespec="seconds"), "complexes": out}


def subscription_items(conn, today: str) -> list[dict]:
    """청약·분양 export 항목 - 접수 예정/진행중 + 최근 1년 내 마감 공고.

    주택형(models)·경쟁률(cmpet)을 공고에 병합한다. 상태 계산은 프런트에서
    날짜로 수행하므로 여기서는 원자료만 담는다.
    """
    cutoff = (datetime.fromisoformat(today) - timedelta(days=365)) \
        .date().isoformat()
    rows = conn.execute(
        """SELECT * FROM subscription
           WHERE rcept_endde IS NULL OR rcept_endde >= ?
           ORDER BY rcept_bgnde DESC""", (cutoff,)).fetchall()
    items = []
    for r in rows:
        hmn = r["house_manage_no"]
        models = []
        for m in conn.execute(
                "SELECT * FROM subscription_model WHERE house_manage_no=? "
                "ORDER BY suply_ar", (hmn,)):
            mo = {
                "ty": m["house_ty"], "ar": m["suply_ar"],
                "hh": m["suply_hshldco"], "shh": m["spsply_hshldco"],
                "price": m["top_amount"],
            }
            # 안전마진: 분양가 vs 주변 반경 같은 평형 최근 실거래
            exclu = _ty_exclu_area(m["house_ty"])
            if m["top_amount"] and r["lat"] and exclu:
                nb = aggregate.nearby_sale_median(conn, r["lat"], r["lon"], exclu)
                if nb:
                    mo["mkt"] = nb["median"]      # 주변 시세(만원)
                    mo["mkt_n"] = nb["n"]
                    mo["mgn"] = round(
                        (nb["median"] - m["top_amount"]) / nb["median"] * 100, 1)
            models.append(mo)
        cmpet = [{
            "ty": c["house_ty"], "resd": c["reside_secd"],
            "req": c["req_cnt"], "rate": c["cmpet_rate"],
        } for c in conn.execute(
            "SELECT * FROM subscription_cmpet WHERE house_manage_no=? "
            "ORDER BY house_ty", (hmn,))]
        items.append({
            "id": hmn, "kind": r["kind"], "secd": r["secd_nm"],
            "src": r["src"] or "api",   # 'web' = 청약홈 캘린더 보조(일정만)
            "name": r["house_nm"],
            "adres": r["adres"], "gu": extract_gu(r["adres"]),
            "lat": r["lat"], "lon": r["lon"],
            "tot": r["tot_suply"],
            "rcrit": r["rcrit_de"],
            "rcept_bgn": r["rcept_bgnde"], "rcept_end": r["rcept_endde"],
            "przwner": r["przwner_de"],
            "cntrct_bgn": r["cntrct_bgnde"], "cntrct_end": r["cntrct_endde"],
            "mvn": r["mvn_ym"], "cnstrct": r["cnstrct_nm"], "url": r["url"],
            "models": models, "cmpet": cmpet,
        })
    return items


def _write_config_js(kakao_js_key: str | None) -> None:
    """프런트에서 읽는 카카오 JS 키 주입 파일."""
    key = kakao_js_key or ""
    path = config.DOCS_DIR / "js" / "config.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'window.KAKAO_JS_KEY = "{key}";\n')
