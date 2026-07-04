"""건축물대장 부가정보 파싱·저장 단위테스트 - 네트워크 없음."""

from seoul_apt import db, building


def test_parse_helpers():
    assert building._int("4,424") == 4424
    assert building._int("0") is None
    assert building._int(None) is None
    assert building._ratio("336.99") == 336.99
    assert building._ratio("0") is None
    assert building._apr_date("20210730") == "2021-07-30"
    assert building._apr_date("") is None
    assert building._apr_date(" ") is None


def test_migrate_and_set_building():
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "개포동", "디에이치자이개포", 2021, "743")
    conn.commit()
    # 마이그레이션으로 컬럼 존재
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(complex)")}
    assert {"households", "far", "bcr", "approval_date", "bldg_fetched_at"} <= cols
    # 조회 대상에 포함(지번 있음)
    assert any(r["complex_id"] == cid
               for r in db.complexes_without_building(conn, "11680"))
    db.set_building(conn, cid, 1996, 336.99, 28.81, "2021-07-30", "2026-07-04T00:00:00")
    conn.commit()
    row = conn.execute("SELECT households, far, bcr, approval_date "
                       "FROM complex WHERE complex_id=?", (cid,)).fetchone()
    assert row["households"] == 1996 and row["far"] == 336.99 and row["bcr"] == 28.81
    # 이제 조회 대상에서 빠짐(bldg_fetched_at 채워짐)
    assert not db.complexes_without_building(conn, "11680")
    conn.close()


def test_fetch_combines_recap_and_title(monkeypatch):
    """총괄표제부에 없는 값을 표제부(동별)로 폴백."""
    client = building.BuildingClient("dk", "kk")
    monkeypatch.setattr(client, "resolve",
                        lambda gu, umd, jibun: {"sigunguCd": "11680",
                        "bjdongCd": "10600", "bun": "0316", "ji": "0000", "platGb": "0"})

    def fake_items(ep, addr):
        if ep == building.RECAP_EP:   # 총괄: 세대수만, 용적률/건폐율 0
            return [{"hhldCnt": "4424", "vlRat": "0", "bcRat": "0", "useAprDay": ""}]
        return [{"hhldCnt": "154", "vlRat": "180.5", "bcRat": "20.1",
                 "useAprDay": "19800526"}]
    monkeypatch.setattr(client, "_get_items", fake_items)

    info = client.fetch("강남구", "대치동", "316")
    assert info["households"] == 4424          # 총괄표제부 값 우선
    assert info["far"] == 180.5                # 표제부 폴백
    assert info["bcr"] == 20.1
    assert info["approval_date"] == "1980-05-26"
