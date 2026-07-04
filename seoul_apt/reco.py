"""AI 추천용 '저평가 후보' 선별 - 파이썬이 수치 근거를 만들고 AI는 정성평가만.

기준(최근 4주 실거래, 해제 제외):
  - discount_pct : 해당 거래 평단가가 단지 최근 1년 평단가 중앙값 대비 몇 % 인지(음수=저가)
  - drop_from_peak_pct : 단지 역대 최고가 대비 하락률
  - jeonse_ratio : 단지 전세가율(최근 전세 중앙값 / 최근 매매 중앙값)
  - volume_x : 단지 거래량 배율(최근 3개월 / 이전 3개월)

후보 조건: 1년 중앙값보다 5% 이상 싸게 거래됐거나 전세가율 70% 이상(갭 작음).
점수 = 저가폭*2 + 전세가율*0.3 + 고점하락*0.5 (높을수록 유망 후보).
날짜 앵커는 DB의 최신 계약일(max deal_date)을 쓴다(재현 가능·데이터 지연 무관).
"""

import json
from datetime import date, timedelta

from . import config
from .aggregate import _median, _pyeong

RECENT_DAYS = 28          # 후보 대상: 최근 4주 거래
MIN_DISCOUNT_PCT = -5.0   # 1년 중앙값 대비 이만큼 싸면 후보
MIN_JEONSE_RATIO = 70.0   # 전세가율 이 이상이면 후보(갭투자 관점)
MIN_CX_SAMPLES = 5        # 단지 1년 매매 표본 최소치(중앙값 신뢰용)
MAX_CANDIDATES = 40


def _iso_minus_days(iso_day: str, days: int) -> str:
    y, m, d = (int(x) for x in iso_day.split("-"))
    return (date(y, m, d) - timedelta(days=days)).isoformat()


def _watch_lawds() -> list[str]:
    """워치리스트의 관심 구 목록. 없으면 서울 전체."""
    from .notify import load_watchlist
    wl = load_watchlist()
    lawds = [w["lawd_cd"] for w in wl.get("watches", []) if w.get("lawd_cd")]
    return sorted(set(lawds)) or list(config.SEOUL_DISTRICTS)


def build_candidates(conn, path=None, lawd_cds=None) -> int:
    """후보를 선별해 JSON 저장. 후보 수 반환."""
    path = path or config.RECO_PATH
    lawd_cds = lawd_cds or _watch_lawds()

    anchor = conn.execute(
        "SELECT MAX(deal_date) AS d FROM sale_txn WHERE canceled=0").fetchone()["d"]
    if not anchor:
        _write(path, anchor, [])
        return 0
    since = _iso_minus_days(anchor, RECENT_DAYS)
    year_ago = _iso_minus_days(anchor, 365)

    candidates = []
    for lawd_cd in lawd_cds:
        deals = conn.execute(
            """SELECT s.id, s.deal_date, s.exclu_area, s.floor, s.amount_manwon,
                      s.complex_id, c.apt_nm, c.umd_nm, c.build_year
               FROM sale_txn s JOIN complex c ON s.complex_id=c.complex_id
               WHERE c.lawd_cd=? AND s.canceled=0 AND s.deal_date >= ?""",
            (lawd_cd, since)).fetchall()

        for d in deals:
            cid = d["complex_id"]
            year_rows = conn.execute(
                """SELECT exclu_area, amount_manwon FROM sale_txn
                   WHERE complex_id=? AND canceled=0 AND deal_date >= ?""",
                (cid, year_ago)).fetchall()
            if len(year_rows) < MIN_CX_SAMPLES:
                continue
            ppys = [r["amount_manwon"] / _pyeong(r["exclu_area"])
                    for r in year_rows if r["exclu_area"]]
            cx_ppy_med = _median(ppys)
            py = _pyeong(d["exclu_area"])
            if not (cx_ppy_med and py > 0):
                continue
            deal_ppy = d["amount_manwon"] / py
            discount = (deal_ppy - cx_ppy_med) / cx_ppy_med * 100

            peak = conn.execute(
                "SELECT MAX(amount_manwon) AS m FROM sale_txn "
                "WHERE complex_id=? AND canceled=0", (cid,)).fetchone()["m"]
            drop_from_peak = ((d["amount_manwon"] - peak) / peak * 100) if peak else 0.0

            jeonse_rows = conn.execute(
                """SELECT deposit_manwon FROM rent_txn
                   WHERE complex_id=? AND rent_type='jeonse'
                   ORDER BY deal_date DESC LIMIT 30""", (cid,)).fetchall()
            jeonse_med = _median([r["deposit_manwon"] for r in jeonse_rows])
            sale_med = _median([r["amount_manwon"] for r in year_rows])
            jeonse_ratio = (round(jeonse_med / sale_med * 100, 1)
                            if jeonse_med and sale_med else None)

            m3 = _iso_minus_days(anchor, 90)
            m6 = _iso_minus_days(anchor, 180)
            recent_vol = conn.execute(
                "SELECT COUNT(*) AS n FROM sale_txn WHERE complex_id=? "
                "AND canceled=0 AND deal_date >= ?", (cid, m3)).fetchone()["n"]
            prior_vol = conn.execute(
                "SELECT COUNT(*) AS n FROM sale_txn WHERE complex_id=? "
                "AND canceled=0 AND deal_date >= ? AND deal_date < ?",
                (cid, m6, m3)).fetchone()["n"]
            volume_x = round(recent_vol / prior_vol, 2) if prior_vol else None

            is_cheap = discount <= MIN_DISCOUNT_PCT
            is_low_gap = jeonse_ratio is not None and jeonse_ratio >= MIN_JEONSE_RATIO
            if not (is_cheap or is_low_gap):
                continue

            score = (-discount) * 2 + (jeonse_ratio or 0) * 0.3 + (-drop_from_peak) * 0.5
            candidates.append({
                "gu": config.SEOUL_DISTRICTS.get(lawd_cd, lawd_cd),
                "lawd_cd": lawd_cd,
                "umd": d["umd_nm"],
                "apt": d["apt_nm"],
                "build_year": d["build_year"],
                "deal_date": d["deal_date"],
                "area_sqm": d["exclu_area"],
                "floor": d["floor"],
                "amount_manwon": d["amount_manwon"],
                "deal_ppy": round(deal_ppy),
                "cx_ppy_median_1y": round(cx_ppy_med),
                "discount_pct": round(discount, 1),
                "peak_amount": peak,
                "drop_from_peak_pct": round(drop_from_peak, 1),
                "jeonse_ratio": jeonse_ratio,
                "sale_count_1y": len(year_rows),
                "volume_x_3m": volume_x,
                "score": round(score, 1),
                "reasons": [t for t, ok in [
                    (f"1년 평단가 대비 {discount:.1f}%", is_cheap),
                    (f"전세가율 {jeonse_ratio}%", is_low_gap),
                ] if ok],
            })

    candidates.sort(key=lambda c: -c["score"])
    candidates = candidates[:MAX_CANDIDATES]
    _write(path, anchor, candidates)
    return len(candidates)


def _write(path, anchor, candidates) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "anchor_date": anchor,
        "window_days": RECENT_DAYS,
        "criteria": {
            "min_discount_pct": MIN_DISCOUNT_PCT,
            "min_jeonse_ratio": MIN_JEONSE_RATIO,
            "min_cx_samples": MIN_CX_SAMPLES,
        },
        "candidates": candidates,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
