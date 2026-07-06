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


def test_sale_by_area_buckets():
    """평형(전용면적 버킷)별 최근 거래 중앙값이 올바르게, 해제 제외로 산출된다."""
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    # ~60㎡ 버킷: 50,55 → 중앙값 52.5억(만원 525000/500000...) 단순화 위해 두 건
    db.insert_sale(conn, cid, "2026-05-01", 49.5, 3, 200000)
    db.insert_sale(conn, cid, "2026-05-02", 55.0, 4, 220000)
    # 60~85㎡ 버킷: 두 건 중앙값
    db.insert_sale(conn, cid, "2026-05-03", 76.79, 5, 300000)
    db.insert_sale(conn, cid, "2026-05-04", 84.0, 6, 320000)
    # 85~135㎡ 버킷: 한 건이지만 해제 → 제외되어 버킷 자체가 없어야 함
    db.insert_sale(conn, cid, "2026-05-05", 120.0, 7, 900000,
                   canceled=1, cancel_date="2026-06-01")
    conn.commit()
    cx = aggregate.complex_list(conn, "11680")[0]
    sba = cx["sale_by_area"]
    assert sba["~60㎡"]["p"] == 210000        # median(200000, 220000)
    assert sba["60~85㎡"]["p"] == 310000      # median(300000, 320000)
    assert "85~135㎡" not in sba              # 해제 건뿐이라 버킷 없음
    assert sba["~60㎡"]["py"] > 0             # 중앙 전용면적(평) 병기
    # 대표 평형: ~60㎡·60~85㎡ 각 2건 동률 → 국민평형대(60~85㎡) 우선
    assert cx["rep"] == "60~85㎡"
    conn.close()


def test_valuation_position():
    """장기 평단가 위치(pos)·전세가율 백분위(jr_pct) 산출 검증."""
    # 24개월 상승 후 하락: 최근가는 5년 범위 중하단
    ppy = [{"m": f"2024-{i:02d}", "v": 3000 + i * 100} for i in range(1, 13)]
    ppy += [{"m": f"2025-{i:02d}", "v": 4200 - i * 50} for i in range(1, 13)]
    jr = [{"y": "2024", "v": 55.0}, {"y": "2025", "v": 70.0}]  # 최근이 역대 최고
    v = aggregate._valuation(ppy, jr)
    assert v["peak"] == 4200 and v["months"] == 24
    assert 0 <= v["pos"] <= 100
    assert v["vs_peak"] < 0                    # 최근가는 고점 아래
    assert v["jr_cur"] == 70.0 and v["jr_pct"] == 100   # 현재가 역대 최고 전세가율
    # 표본 부족 시 None
    assert aggregate._valuation(ppy[:6], []) is None


def test_by_area_jeonse_and_stale():
    """전세 평형별 대표가(deal_date 필요)와 1년+ 오래된 거래 stale 표시 검증."""
    from datetime import date, timedelta
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    recent = (date.today() - timedelta(days=20)).isoformat()
    old = (date.today() - timedelta(days=800)).isoformat()   # 1년 밖
    # 60~85㎡: 최근 매매 → stale 아님
    db.insert_sale(conn, cid, recent, 76.79, 5, 300000)
    # ~60㎡: 1년 넘은 매매뿐 → 최근가 대체 + s=1
    db.insert_sale(conn, cid, old, 49.5, 3, 150000)
    # 전세(60~85㎡) 최근 1건 - deal_date 를 쓰므로 쿼리에 컬럼 포함돼야 함
    db.insert_rent(conn, cid, recent, 76.79, 4, 200000, 0)   # 월세 0 → 전세
    conn.commit()
    cx = aggregate.complex_list(conn, "11680")[0]
    assert cx["sale_by_area"]["60~85㎡"].get("s") is None      # 최근 → 정상
    assert cx["sale_by_area"]["~60㎡"]["s"] == 1               # 오래됨
    assert cx["jeonse_by_area"]["60~85㎡"]["p"] == 200000      # 전세 대표가
    assert cx["jrep"] == "60~85㎡"
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


def test_complex_list_filter_fields_and_peak_share():
    """필터용 필드(n1y·drop)와 구별 신고가 비중 산출 검증."""
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    # 과거 거래(1년 밖) 2건 + 최근 거래 3건(마지막이 신고가)
    db.insert_sale(conn, cid, "2020-01-10", 76.79, 3, 200000)
    db.insert_sale(conn, cid, "2020-02-10", 76.79, 5, 210000)
    from datetime import date, timedelta
    recent = [(date.today() - timedelta(days=10 * i)).isoformat() for i in (3, 2, 1)]
    db.insert_sale(conn, cid, recent[0], 76.79, 7, 250000)
    db.insert_sale(conn, cid, recent[1], 76.79, 9, 300000)   # 역대 최고가(중간)
    db.insert_sale(conn, cid, recent[2], 76.79, 11, 260000)  # 최근 1건(고점 아래)
    conn.commit()

    cx = aggregate.complex_list(conn, "11680")[0]
    assert cx["sale_1y"] == 3                     # 최근 1년 거래만 카운트
    assert cx["households"] is None               # 건축물대장 미수집 상태
    # 최근 1건(260000)이 고점(300000) 대비 하락 → drop_pct 음수, 신고가 아님
    assert cx["is_peak"] is False
    assert cx["drop_pct"] is not None and cx["drop_pct"] < 0

    ps = aggregate.district_peak_share(conn, days=90)
    gang = next(p for p in ps if p["lawd_cd"] == "11680")
    assert gang["total"] == 3                     # 최근 90일 거래 3건
    assert gang["peaks"] == 1                     # 그중 신고가 1건
    assert gang["share"] == round(1 / 3 * 100, 1)
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
