"""수집 오케스트레이터 - 일일 증분 + 재개가능 백필.

일일: 각 구의 최근 N개월(신고 지연/정정 대응)을 재수집.
백필: 시작월~현재를 순회하되 fetch_log 에 기록된 (구,월,종류)는 건너뛴다.
"""

from datetime import datetime, timezone, timedelta

from . import config, db
from .molit_api import MolitClient

KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def _ym_iter(start_ym: str, end_ym: str):
    """'YYYYMM' 시작~끝(포함)을 순회."""
    y, m = int(start_ym[:4]), int(start_ym[4:6])
    ey, em = int(end_ym[:4]), int(end_ym[4:6])
    while (y, m) <= (ey, em):
        yield f"{y:04d}{m:02d}"
        m += 1
        if m > 12:
            m = 1
            y += 1


def _recent_yms(months: int) -> list[str]:
    now = _now_kst()
    y, m = now.year, now.month
    out = []
    for _ in range(months):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    return out


def collect_month(conn, client: MolitClient, lawd_cd: str, ymd: str) -> tuple[int, int]:
    """한 구·한 달의 매매+전월세를 수집. (매매건수, 전월세건수) 반환."""
    fetched_at = _now_kst().isoformat(timespec="seconds")

    sales = client.fetch_sales(lawd_cd, ymd)
    for s in sales:
        cid = db.upsert_complex(conn, lawd_cd, s["umd_nm"], s["apt_nm"],
                                s["build_year"], s["jibun"])
        db.insert_sale(conn, cid, s["deal_date"], s["exclu_area"],
                       s["floor"], s["amount_manwon"],
                       canceled=s.get("canceled", 0),
                       cancel_date=s.get("cancel_date"),
                       deal_gbn=s.get("deal_gbn"))
    db.record_fetch(conn, lawd_cd, ymd, "sale", fetched_at, len(sales))

    rents = client.fetch_rents(lawd_cd, ymd)
    for r in rents:
        cid = db.upsert_complex(conn, lawd_cd, r["umd_nm"], r["apt_nm"],
                                r["build_year"], r["jibun"])
        db.insert_rent(conn, cid, r["deal_date"], r["exclu_area"], r["floor"],
                       r["deposit_manwon"], r["monthly_manwon"])
    db.record_fetch(conn, lawd_cd, ymd, "rent", fetched_at, len(rents))

    conn.commit()
    return len(sales), len(rents)


def run_daily(conn, service_key: str, lookback: int | None = None) -> dict:
    """일일 증분 수집 - 최근 N개월 재수집."""
    client = MolitClient(service_key)
    lookback = lookback or config.DAILY_LOOKBACK_MONTHS
    yms = _recent_yms(lookback)
    stats = {"months": yms, "sale": 0, "rent": 0}
    for lawd_cd, name in config.SEOUL_DISTRICTS.items():
        for ymd in yms:
            s, r = collect_month(conn, client, lawd_cd, ymd)
            stats["sale"] += s
            stats["rent"] += r
            print(f"[daily] {name}({lawd_cd}) {ymd}: 매매 {s}, 전월세 {r}")
    return stats


def run_backfill(conn, service_key: str, start_ym: str | None = None,
                 end_ym: str | None = None, force: bool = False) -> dict:
    """백필 - 시작월~끝월 순회, fetch_log 로 재개."""
    client = MolitClient(service_key)
    start_ym = start_ym or config.BACKFILL_START_YM
    end_ym = end_ym or _now_kst().strftime("%Y%m")
    stats = {"start": start_ym, "end": end_ym, "sale": 0, "rent": 0, "skipped": 0}
    for lawd_cd, name in config.SEOUL_DISTRICTS.items():
        for ymd in _ym_iter(start_ym, end_ym):
            if not force and db.already_fetched(conn, lawd_cd, ymd, "sale") \
                    and db.already_fetched(conn, lawd_cd, ymd, "rent"):
                stats["skipped"] += 1
                continue
            s, r = collect_month(conn, client, lawd_cd, ymd)
            stats["sale"] += s
            stats["rent"] += r
            print(f"[backfill] {name}({lawd_cd}) {ymd}: 매매 {s}, 전월세 {r}")
    return stats
