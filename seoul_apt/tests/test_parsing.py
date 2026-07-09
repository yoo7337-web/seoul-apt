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


def test_paged_items_no_early_break_on_unparsable_total_count():
    """totalCount 파싱 실패(0으로 대체되던 과거 버그) 시 첫 페이지가 꽉 차도
    즉시 중단돼 초과분이 유실되면 안 된다(사고 이력 회귀 테스트) - 페이지가
    NUM_OF_ROWS 미만으로 돌아올 때까지 계속 조회해야 한다."""
    def make_root(n_items, bad_total=False):
        items = "".join("<item><x>1</x></item>" for _ in range(n_items))
        total = "<totalCount>abc</totalCount>" if bad_total else ""
        return ET.fromstring(f"<response><body>{total}{items}</body></response>")

    client = MolitClient("dummy")
    pages = {
        1: make_root(config.NUM_OF_ROWS, bad_total=True),  # 꽉 찬 페이지 + 파싱불가 총계
        2: make_root(5),                                    # 마지막 페이지(미달)
    }
    calls = []

    def fake_get_xml(ep, params):
        calls.append(params["pageNo"])
        return pages[params["pageNo"]]
    client._get_xml = fake_get_xml

    items = list(client._paged_items("http://x", "11680", "202601"))
    assert calls == [1, 2]                          # 2페이지 모두 조회돼야 함
    assert len(items) == config.NUM_OF_ROWS + 5      # 유실 없이 전부 수집


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


def test_recent_bargains():
    """대시보드 급매: 최근 N일 창에서 동일평형 중앙값 -7%↓ 수집(저층 제외)."""
    from datetime import date
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    today = date.today().isoformat()
    for i in range(6):
        db.insert_sale(conn, cid, today, 84.0, 5 + i, 120000)  # 기준 표본
    db.insert_sale(conn, cid, today, 84.1, 10, 108000)         # 급매(-10%, 10층)
    db.insert_sale(conn, cid, today, 84.2, 1, 100000)          # 1층 → 제외
    conn.commit()
    bargains = aggregate.recent_bargains(conn, days=45)
    floors = [b["floor"] for b in bargains]
    assert 10 in floors and 1 not in floors
    b = next(x for x in bargains if x["floor"] == 10)
    assert b["disc"] == -10.0 and b["id"] == cid and b["lawd_cd"] == "11680"
    conn.close()


def test_buyer_outsider_rows():
    """매입자거주지별 pivot → 외지인 비중(%) 계산 검증."""
    from seoul_apt import reb_api
    mk = lambda grp, grpnm, cls, val: {
        "GRP_FULLNM": grp, "GRP_NM": grpnm, "CLS_FULLNM": cls,
        "DTA_VAL": val, "WRTTIME_IDTFR_ID": "202605"}
    rows = [
        mk("서울>강남구", "강남구", "합계", 100),
        mk("서울>강남구", "강남구", "관할시군구내", 40),
        mk("서울>강남구", "강남구", "관할시도내", 30),
        mk("서울>강남구", "강남구", "관할시도외_기타", 30),
        mk("서울>서초구", "서초구", "합계", 200),
        mk("서울>서초구", "서초구", "관할시군구내", 100),
        mk("서울>서초구", "서초구", "관할시도내", 60),
        mk("충북>청주시>상당구", "상당구", "합계", 220),   # 서울 구 아님 → 제외
        mk("서울>중구", "중구", "합계", 5),                # 구별 표본<10 제외, 서울 합산엔 포함
    ]
    out = dict(((r, p), v) for r, p, v in reb_api._buyer_outsider_rows(rows))
    assert out[("강남구", "2026-05")] == 30.0     # (100-70)/100
    assert out[("서초구", "2026-05")] == 20.0     # (200-160)/200
    assert out[("서울", "2026-05")] == 24.6       # (305-230)/305, 25개구 합산
    assert ("상당구", "2026-05") not in out
    assert ("중구", "2026-05") not in out         # 구별로는 표본 부족


def test_market_phase_classification():
    """4국면 판정: 거래량×가격 모멘텀 조합."""
    p = aggregate._phase
    assert p(1.2, 5.0) == "boom"        # 거래↑ 가격↑
    assert p(1.2, -5.0) == "recovery"   # 거래↑ 가격↓
    assert p(0.8, 5.0) == "slowdown"    # 거래↓ 가격↑
    assert p(0.8, -5.0) == "recession"  # 거래↓ 가격↓
    assert p(1.0, 0.0) == "neutral"     # 경계
    assert p(None, 5.0) == "neutral"    # 데이터 부족


def test_bargain_deals():
    """급매 감지: 동일평형 중앙값 대비 -7%↓, 저층 제외."""
    from datetime import date
    from seoul_apt import notify
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    today = date.today().isoformat()
    # 기준 표본 6건(84㎡ 12억)
    for i in range(6):
        db.insert_sale(conn, cid, today, 84.0, 5 + i, 120000)
    # 급매 후보: 84㎡ 10.8억(-10%), 10층 → 감지
    db.insert_sale(conn, cid, today, 84.1, 10, 108000)
    # 저층 급매(1층 10.8억) → 제외돼야 함
    db.insert_sale(conn, cid, today, 84.2, 1, 108000)
    conn.commit()
    rows = notify.new_sales(conn, 0)
    bargains = notify.bargain_deals(conn, rows)
    floors = [b["row"]["floor"] for b in bargains]
    assert 10 in floors and 1 not in floors        # 10층만 급매, 1층 제외
    b10 = next(b for b in bargains if b["row"]["floor"] == 10)
    assert b10["disc"] == -10.0
    conn.close()


def test_matched_jeonse_ratio():
    """전세가율은 같은 크기(대표 전용면적 ±12%) 전세/매매로 산출, 혼합 왜곡 방지."""
    # 매매: 84㎡ 12억(3건), 대형 178㎡ 40억(섞임). 전세: 84㎡ 8억, 178㎡ 20억.
    sale = ([{"exclu_area": 84.0, "amount_manwon": 120000}] * 3
            + [{"exclu_area": 178.0, "amount_manwon": 400000}] * 3)
    jeonse = ([{"exclu_area": 84.0, "deposit_manwon": 80000}] * 3
              + [{"exclu_area": 178.0, "deposit_manwon": 200000}] * 3)
    # 대표 84㎡ ±12%: 전세 8억 / 매매 12억 = 66.7% (혼합이면 왜곡)
    assert aggregate._matched_jeonse_ratio(sale, jeonse, 84.0) == 66.7
    # 178㎡ 기준: 20억/40억 = 50%
    assert aggregate._matched_jeonse_ratio(sale, jeonse, 178.0) == 50.0
    # 표본 부족 시 None
    assert aggregate._matched_jeonse_ratio(sale, jeonse[:1], 84.0) is None


def test_valuation_position():
    """장기 평단가 위치(pos)·절대 전세가율(jr) 산출 검증."""
    # 24개월 상승 후 하락: 최근가는 5년 범위 중하단
    ppy = [{"m": f"2024-{i:02d}", "v": 3000 + i * 100} for i in range(1, 13)]
    ppy += [{"m": f"2025-{i:02d}", "v": 4200 - i * 50} for i in range(1, 13)]
    v = aggregate._valuation(ppy, 62.5)
    assert v["peak"] == 4200 and v["months"] == 24
    assert 0 <= v["pos"] <= 100
    assert v["vs_peak"] < 0                    # 최근가는 고점 아래
    assert v["jr"] == 62.5                     # 절대 전세가율 그대로 전달
    # 표본 12개월 미만이면 None
    assert aggregate._valuation(ppy[:6], None) is None


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


def test_peak_matched_by_size():
    """신고가 판정은 비슷한 크기(±12%)끼리 비교 - 대형 평형 역대가가
    소형 평형의 진짜 신고가를 가리면 안 된다(사고 이력 회귀 테스트)."""
    from datetime import date
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    today = date.today().isoformat()
    # 대형(135㎡) 역대 최고 20억(오래전) - 전 평형 혼합이면 이게 "역대 최고가"로 잡힘
    db.insert_sale(conn, cid, "2020-01-10", 135.0, 10, 200000)
    # 소형(59㎡) 과거 8억 → 최근 9억(59㎡ 안에서는 신고가, 20억보다는 훨씬 낮음)
    db.insert_sale(conn, cid, "2021-01-10", 59.0, 3, 80000)
    db.insert_sale(conn, cid, today, 59.0, 5, 90000)
    conn.commit()

    cx = aggregate.complex_list(conn, "11680")[0]
    assert cx["is_peak"] is True        # 59㎡ 기준으로는 신고가여야 함
    assert cx["peak_amount"] == 90000    # 135㎡ 20억에 가려지면 안 됨
    conn.close()


def test_district_peak_share_matched_by_size():
    """구별 신고가 비중도 크기 매칭 - 표본 부족한 크기(대형 1건)는 신고가 판정 제외."""
    from datetime import date, timedelta
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    anchor = date.today()
    for i, amt in enumerate([80000, 82000, 85000, 90000]):
        d = (anchor - timedelta(days=10 * (4 - i))).isoformat()
        db.insert_sale(conn, cid, d, 59.0, 3 + i, amt)
    # 대형(135㎡) 1건은 같은 크기 표본<3이라 신고가 판정에서 제외돼야 함
    db.insert_sale(conn, cid, anchor.isoformat(), 135.0, 20, 500000)
    conn.commit()

    ps = aggregate.district_peak_share(conn, days=90)
    gang = next(p for p in ps if p["lawd_cd"] == "11680")
    assert gang["total"] == 5
    assert gang["peaks"] == 1   # 59㎡ 마지막 거래(90000)만 그 크기 내 신고가
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
