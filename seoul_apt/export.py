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
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import config, aggregate

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
                    "jeonse": c["jeonse_median"],
                    "jeonse_area": c["jeonse_by_area"],
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
    # 대시보드 전용 데이터(구별 평단가 추이 + 신고가 비중)
    _write_json(export_dir / "dashboard.json", {
        "generated": now.isoformat(timespec="seconds"),
        "ppy_trend": ppy_trend,
        "peak_share": aggregate.district_peak_share(conn, days=90),
        "peak_share_days": 90,
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


def _write_config_js(kakao_js_key: str | None) -> None:
    """프런트에서 읽는 카카오 JS 키 주입 파일."""
    key = kakao_js_key or ""
    path = config.DOCS_DIR / "js" / "config.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'window.KAKAO_JS_KEY = "{key}";\n')
