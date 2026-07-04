"""API 파싱·집계 단위테스트 (네트워크 없이 fixture 사용)."""

import xml.etree.ElementTree as ET
from pathlib import Path

from seoul_apt import db, aggregate, config
from seoul_apt.molit_api import MolitClient, _to_int

FIX = Path(__file__).parent / "fixtures"


def _client_with(fixture_name):
    root = ET.fromstring((FIX / fixture_name).read_bytes())
    client = MolitClient("dummy")
    client._get_xml = lambda ep, params: root  # 네트워크 대체
    return client


def test_parse_sales():
    client = _client_with("sample_trade.xml")
    rows = client.fetch_sales("11680", "202605")
    assert len(rows) == 3
    r = rows[0]
    assert r["apt_nm"] == "래미안대치팰리스"
    assert r["amount_manwon"] == 350000
    assert r["exclu_area"] == 84.99
    assert r["deal_date"] == "2026-05-12"
    assert r["canceled"] == 0 and r["cancel_date"] is None


def test_parse_canceled_deal():
    client = _client_with("sample_trade.xml")
    rows = client.fetch_sales("11680", "202605")
    canceled = [r for r in rows if r["canceled"]]
    assert len(canceled) == 1
    c = canceled[0]
    assert c["amount_manwon"] == 990000
    assert c["cancel_date"] == "2026-05-20"       # '26.05.20' → ISO 변환
    normal = [r for r in rows if not r["canceled"]]
    assert {r["deal_gbn"] for r in normal} == {None, "중개거래"}


def test_cancel_date_formats():
    from seoul_apt.molit_api import _cancel_date
    assert _cancel_date("25.01.03") == "2025-01-03"
    assert _cancel_date(" ") is None
    assert _cancel_date(None) is None
    assert _cancel_date("2025.1.3") == "2025-01-03"


def test_parse_rents_classification():
    client = _client_with("sample_rent.xml")
    rows = client.fetch_rents("11680", "202605")
    assert len(rows) == 2
    jeonse = [r for r in rows if r["monthly_manwon"] == 0]
    wolse = [r for r in rows if r["monthly_manwon"] > 0]
    assert len(jeonse) == 1 and jeonse[0]["deposit_manwon"] == 180000
    assert len(wolse) == 1 and wolse[0]["monthly_manwon"] == 120


def test_to_int_handles_commas_and_blanks():
    assert _to_int("350,000") == 350000
    assert _to_int(" ") is None
    assert _to_int("-") is None
    assert _to_int(None) is None


def test_normalize_apt_name():
    assert db.normalize_apt_name("래미안 대치팰리스(101동)") == "래미안대치팰리스"
    assert db.normalize_apt_name("은마 - 아파트") == "은마아파트"


def test_area_bucket():
    assert config.area_bucket(59) == "~60㎡"
    assert config.area_bucket(84.99) == "60~85㎡"
    assert config.area_bucket(120) == "85~135㎡"
    assert config.area_bucket(200) == "135㎡~"


def test_aggregate_ppy_and_jeonse_ratio():
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    db.insert_sale(conn, cid, "2026-05-01", 76.79, 3, 270000)
    db.insert_rent(conn, cid, "2026-05-02", 76.79, 5, 50000, 0)  # 전세
    conn.commit()
    monthly = aggregate.district_monthly(conn, "11680")
    assert monthly[-1]["sale_median"] == 270000
    assert monthly[-1]["jeonse_median"] == 50000
    # 평단가 = 270000 / (76.79 * (1/3.305785)) 평
    assert monthly[-1]["ppy_median"] > 0
    assert monthly[-1]["jeonse_ratio"] == round(50000 / 270000 * 100, 1)
    conn.close()


def test_canceled_excluded_from_stats():
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    db.insert_sale(conn, cid, "2026-05-01", 76.79, 3, 270000)
    db.insert_sale(conn, cid, "2026-05-07", 76.79, 9, 990000, canceled=1,
                   cancel_date="2026-05-20")
    conn.commit()
    # 월별 통계·구 최근거래·단지 대표가에서 해제건 제외
    monthly = aggregate.district_monthly(conn, "11680")
    assert monthly[-1]["sale_median"] == 270000
    assert monthly[-1]["sale_count"] == 1
    recent = aggregate.district_recent_txns(conn, "11680")
    assert [r["amount"] for r in recent] == [270000]
    cx = aggregate.complex_list(conn, "11680")[0]
    assert cx["peak_amount"] == 270000  # 해제된 99억이 신고가로 잡히면 안 됨
    # 단지 상세 최근거래에는 해제건이 플래그와 함께 포함
    detail = aggregate.complex_detail(conn, cid)
    flags = {r["amount"]: r["canceled"] for r in detail["recent_sales"]}
    assert flags == {270000: 0, 990000: 1}
    conn.close()


def test_upsert_updates_cancel_status():
    """같은 거래가 나중에 해제로 재수집되면 canceled 가 갱신되어야 한다."""
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    db.insert_sale(conn, cid, "2026-05-01", 76.79, 3, 270000)          # 최초 정상
    db.insert_sale(conn, cid, "2026-05-01", 76.79, 3, 270000,          # 재수집: 해제됨
                   canceled=1, cancel_date="2026-06-01")
    conn.commit()
    rows = conn.execute("SELECT canceled, cancel_date FROM sale_txn").fetchall()
    assert len(rows) == 1                       # 중복 행 없이
    assert rows[0]["canceled"] == 1             # 상태만 갱신
    assert rows[0]["cancel_date"] == "2026-06-01"
    conn.close()


def test_migrate_old_db_adds_columns(tmp_path):
    """canceled 컬럼이 없는 구버전 DB도 connect() 시 마이그레이션된다."""
    import sqlite3
    old = tmp_path / "old.sqlite"
    raw = sqlite3.connect(str(old))
    raw.execute("""CREATE TABLE sale_txn (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complex_id INTEGER NOT NULL, deal_date TEXT NOT NULL,
        exclu_area REAL NOT NULL, floor INTEGER,
        amount_manwon INTEGER NOT NULL,
        UNIQUE(complex_id, deal_date, exclu_area, floor, amount_manwon))""")
    raw.execute("INSERT INTO sale_txn (complex_id, deal_date, exclu_area, floor, amount_manwon) "
                "VALUES (1, '2026-01-01', 84.9, 5, 100000)")
    raw.commit()
    raw.close()
    conn = db.connect(old)
    row = conn.execute("SELECT canceled, cancel_date, deal_gbn FROM sale_txn").fetchone()
    assert row["canceled"] == 0 and row["cancel_date"] is None
    conn.close()
