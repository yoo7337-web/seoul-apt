"""매물(호가) 수집 단위테스트 - 네트워크 없음(가짜 클라이언트 사용)."""

from datetime import date, timedelta

from seoul_apt import db, listings


def _seed_complex(conn, apt="은마", lawd="11680", umd="대치동", lat=37.4974, lon=127.0653):
    cid = db.upsert_complex(conn, lawd, umd, apt, 1979, "316")
    conn.execute("UPDATE complex SET lat=?, lon=? WHERE complex_id=?", (lat, lon, cid))
    conn.commit()
    return cid


class _FakeNaver:
    """search_complex 만 흉내내는 가짜 클라이언트(매칭 로직 테스트용)."""

    def __init__(self, results_by_query):
        self.results = results_by_query
        self.queries = []

    def search_complex(self, name):
        self.queries.append(name)
        return self.results.get(name, [])


def test_match_by_coordinate_and_name():
    conn = db.connect(":memory:")
    cid = _seed_complex(conn)
    client = _FakeNaver({"은마": [
        {"no": "236", "name": "은마", "lat": 37.4976, "lon": 127.0650},   # ~25m
        {"no": "999", "name": "은마상가", "lat": 37.5200, "lon": 127.1000},  # 멀리
    ]})
    assert listings.match_naver_no(conn, cid, "은마", 37.4974, 127.0653, client) == "236"
    conn.close()


def test_match_rejects_far_complex():
    """이름이 비슷해도 좌표가 멀면(>120m) 매칭하지 않는다 - 동명 단지 오매칭 방지."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn)
    client = _FakeNaver({"은마": [
        {"no": "999", "name": "은마", "lat": 37.5500, "lon": 127.1200},   # 수 km
    ]})
    assert listings.match_naver_no(conn, cid, "은마", 37.4974, 127.0653, client) is None
    conn.close()


def test_match_strips_parens_and_retries():
    """괄호가 든 단지명은 네이버 검색이 0건 → 괄호 제거 후 재검색한다."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn, apt="경희궁자이(2단지)", lat=37.5707, lon=127.0000)
    client = _FakeNaver({
        "경희궁자이(2단지)": [],                       # 원본은 0건
        "경희궁자이": [{"no": "109379", "name": "경희궁자이2단지",
                        "lat": 37.5708, "lon": 127.0000}],   # ~11m
    })
    no = listings.match_naver_no(conn, cid, "경희궁자이(2단지)", 37.5707, 127.0000, client)
    assert no == "109379"
    assert client.queries == ["경희궁자이(2단지)", "경희궁자이"]
    conn.close()


def test_match_by_coordinate_when_name_differs():
    """표기차(쥬↔주 등)로 이름이 안 맞아도 좌표 초근접(≤50m)이면 채택."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn, apt="효성쥬얼리시티", lat=37.5715, lon=126.9987)
    client = _FakeNaver({"효성쥬얼리시티": [
        {"no": "17286", "name": "효성주얼리시티", "lat": 37.5715, "lon": 126.9987},
    ]})
    assert listings.match_naver_no(
        conn, cid, "효성쥬얼리시티", 37.5715, 126.9987, client) == "17286"
    conn.close()


def test_parse_naver_article_sale_and_jeonse():
    sale = listings._parse_naver_article({
        "representativeArticleInfo": {
            "articleNumber": "123", "dongName": "101", "tradeType": "A1",
            "spaceInfo": {"exclusiveSpace": 76.79},
            "articleDetail": {"direction": "SS",
                              "floorDetailInfo": {"targetFloor": "5", "totalFloor": "14"}},
            "verificationInfo": {"articleConfirmDate": "2026-07-08"},
            "priceInfo": {"dealPrice": 3400000000, "warrantyPrice": 0, "rentPrice": 0},
        }}, "236")
    assert sale["trade_type"] == "sale"
    assert sale["price_manwon"] == 340000       # 34억 → 만원
    assert sale["area_m2"] == 76.79 and sale["floor"] == 5 and sale["floor_total"] == 14
    assert sale["direction"] == "남"
    assert "articleNo=123" in sale["url"]

    jeonse = listings._parse_naver_article({
        "representativeArticleInfo": {
            "articleNumber": "456", "tradeType": "B1",
            "spaceInfo": {"exclusiveSpace": 76.79},
            "articleDetail": {"floorDetailInfo": {}},
            "verificationInfo": {},
            "priceInfo": {"dealPrice": 0, "warrantyPrice": 700000000, "rentPrice": 0},
        }}, "236")
    assert jeonse["trade_type"] == "jeonse" and jeonse["price_manwon"] == 70000


def test_asking_premium_matched_by_size():
    """호가 괴리도 같은 크기(±12%)·최근 1년 실거래로만 비교(대원칙)."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn)
    recent = (date.today() - timedelta(days=30)).isoformat()
    # 소형(59㎡) 실거래 8억 3건
    for i in range(3):
        db.insert_sale(conn, cid, recent, 59.0, 3 + i, 80000)
    # 대형(135㎡) 실거래 20억 3건 — 섞이면 안 됨
    for i in range(3):
        db.insert_sale(conn, cid, recent, 135.0, 5 + i, 200000)
    conn.commit()
    # 59㎡ 호가 9억 → 소형끼리 비교하면 +12.5%
    prem = listings.asking_premium(conn, cid, 59.0, 90000, "sale")
    assert prem == 12.5
    conn.close()


def test_asking_premium_needs_sample():
    conn = db.connect(":memory:")
    cid = _seed_complex(conn)
    recent = (date.today() - timedelta(days=30)).isoformat()
    db.insert_sale(conn, cid, recent, 59.0, 3, 80000)   # 1건뿐 → 표본 부족
    conn.commit()
    assert listings.asking_premium(conn, cid, 59.0, 90000, "sale") is None
    # 전세 호가는 계산 안 함(매매 실거래와 비교 불가)
    assert listings.asking_premium(conn, cid, 59.0, 70000, "jeonse") is None
    conn.close()


def _rec(item_id, price, trade="sale", area=76.79):
    return {"source": "naver", "item_id": item_id, "trade_type": trade,
            "price_manwon": price, "monthly_manwon": 0, "area_m2": area,
            "floor": 5, "floor_total": 14, "dong": "101", "direction": "남",
            "description": None, "confirm_date": "2026-07-08", "url": "u"}


def test_upsert_marks_gone_when_delisted():
    """이전 스냅샷에 있었는데 이번에 없는 매물은 gone(이력 보존)."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn)
    listings.upsert_listings(conn, cid, [_rec("a", 340000), _rec("b", 350000)], "t1")
    assert conn.execute("SELECT COUNT(*) FROM listing WHERE status='open'").fetchone()[0] == 2
    # 두번째 수집에서 'b'가 사라짐
    out = listings.upsert_listings(conn, cid, [_rec("a", 339000)], "t2")
    assert out["gone"] == 1
    a = conn.execute("SELECT price_manwon, status FROM listing WHERE item_id='a'").fetchone()
    b = conn.execute("SELECT status FROM listing WHERE item_id='b'").fetchone()
    assert a["price_manwon"] == 339000 and a["status"] == "open"   # 가격 갱신
    assert b["status"] == "gone"                                   # 삭제 아닌 gone
    conn.close()


def test_upsert_revives_relisted():
    """gone 이던 매물이 다시 올라오면 open 으로 복구."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn)
    listings.upsert_listings(conn, cid, [_rec("a", 340000)], "t1")
    listings.upsert_listings(conn, cid, [], "t2")
    assert conn.execute("SELECT status FROM listing WHERE item_id='a'").fetchone()[0] == "gone"
    listings.upsert_listings(conn, cid, [_rec("a", 335000)], "t3")
    assert conn.execute("SELECT status FROM listing WHERE item_id='a'").fetchone()[0] == "open"
    conn.close()


def test_state_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "listings_state.json"
    monkeypatch.setattr(listings, "STATE_PATH", p)
    assert listings.load_state() == {"done_complex_ids": []}
    listings.save_state({"done_complex_ids": [1, 2]})
    assert listings.load_state()["done_complex_ids"] == [1, 2]
