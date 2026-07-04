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
    assert len(rows) == 2
    r = rows[0]
    assert r["apt_nm"] == "래미안대치팰리스"
    assert r["amount_manwon"] == 350000
    assert r["exclu_area"] == 84.99
    assert r["deal_date"] == "2026-05-12"


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
