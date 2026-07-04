"""DB 멱등성·매칭 단위테스트."""

from seoul_apt import db, gongsi


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def test_districts_seeded():
    conn = db.connect(":memory:")
    assert _count(conn, "district") == 25
    conn.close()


def test_sale_insert_idempotent():
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    for _ in range(3):  # 같은 거래 3번 삽입
        db.insert_sale(conn, cid, "2026-05-01", 76.79, 3, 270000)
    conn.commit()
    assert _count(conn, "sale_txn") == 1  # 중복 제거됨
    conn.close()


def test_complex_dedup_by_normalized_name():
    conn = db.connect(":memory:")
    a = db.upsert_complex(conn, "11680", "대치동", "래미안 대치팰리스", 2015, "1")
    b = db.upsert_complex(conn, "11680", "대치동", "래미안대치팰리스", 2015, "1")
    assert a == b  # 정규화로 동일 단지 인식
    assert _count(conn, "complex") == 1
    conn.close()


def test_rent_type_split():
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    db.insert_rent(conn, cid, "2026-05-01", 76.79, 3, 180000, 0)    # 전세
    db.insert_rent(conn, cid, "2026-05-02", 76.79, 5, 50000, 120)   # 월세
    conn.commit()
    types = {r["rent_type"] for r in conn.execute("SELECT rent_type FROM rent_txn")}
    assert types == {"jeonse", "wolse"}
    conn.close()


def test_gongsi_price_parse():
    # 원 단위 → 만원 변환
    assert gongsi._parse_price("1,250,000,000") == 125000
    assert gongsi._parse_price("") is None


def test_fetch_log_resume():
    conn = db.connect(":memory:")
    assert not db.already_fetched(conn, "11680", "202605", "sale")
    db.record_fetch(conn, "11680", "202605", "sale", "2026-06-01T09:00:00", 10)
    conn.commit()
    assert db.already_fetched(conn, "11680", "202605", "sale")
    conn.close()
