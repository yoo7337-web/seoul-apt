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
    totals = {"sale": 0, "rent": 0, "complex": 0}

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
                })

    _write_json(export_dir / "markers.json", {"markers": markers})
    _write_json(export_dir / "reb" / "seoul_index.json",
                aggregate.reb_series(conn))
    # 청약·분양(진행중 + 최근 1년 마감분)
    _write_json(export_dir / "subscription.json", {
        "generated": now.isoformat(timespec="seconds"),
        "items": subscription_items(conn, now.date().isoformat()),
    })
    # 대시보드 전용 데이터(구별 평단가 추이 + 신고가 비중)
    _write_json(export_dir / "dashboard.json", {
        "generated": now.isoformat(timespec="seconds"),
        "ppy_trend": ppy_trend,
        "peak_share": aggregate.district_peak_share(conn, days=90),
        "peak_share_days": 90,
        "market_phase": aggregate.market_phase(conn),
    })
    _write_json(export_dir / "meta.json", {
        "last_updated": now.isoformat(timespec="seconds"),
        "last_updated_display": now.strftime("%Y-%m-%d %H:%M KST"),
        "districts": district_list,
        "rankings": aggregate.district_rankings(conn),
        "totals": totals,
        "marker_count": len(markers),
    })

    _write_config_js(kakao_js_key)
    return {"markers": len(markers), **totals}


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
            "id": hmn, "kind": r["kind"], "name": r["house_nm"],
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
