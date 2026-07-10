"""입지 레이어(poi) 최근접 계산 단위테스트 - 네트워크 없음."""

from seoul_apt import db, poi


def _seed_complex(conn, lawd, umd, apt, lat, lon):
    cid = db.upsert_complex(conn, lawd, umd, apt, 2000, "1")
    conn.execute("UPDATE complex SET lat=?, lon=? WHERE complex_id=?", (lat, lon, cid))
    conn.commit()
    return cid


def _add_poi(conn, kind, name, line, lat, lon):
    conn.execute("INSERT INTO poi(kind, name, line, lat, lon) VALUES (?,?,?,?,?)",
                 (kind, name, line, lat, lon))
    conn.commit()


def test_nearest_picks_closest_and_labels_line():
    conn = db.connect(":memory:")
    # 강남역 인근 가상 단지
    cid = _seed_complex(conn, "11680", "역삼동", "테스트단지", 37.4979, 127.0276)
    _add_poi(conn, "subway", "강남", "2호선", 37.4979, 127.0276)      # 바로 위(0m)
    _add_poi(conn, "subway", "역삼", "2호선", 37.5006, 127.0365)      # 약 800m
    _add_poi(conn, "elem", "역삼초등학교", None, 37.4990, 127.0300)    # 약 250m
    _add_poi(conn, "elem", "도곡초등학교", None, 37.4900, 127.0500)    # 멀리
    out = poi.compute_nearest(conn, refresh=True)
    assert out["updated"] == 1
    r = conn.execute(
        "SELECT subway_m, subway_nm, school_m FROM complex WHERE complex_id=?",
        (cid,)).fetchone()
    assert r["subway_m"] == 0                       # 강남역이 최근접
    assert r["subway_nm"] == "강남·2호선"            # 노선 병기
    assert 200 <= r["school_m"] <= 320              # 역삼초가 최근접(~250m)
    conn.close()


def test_beyond_max_is_null():
    """상한(2km/1.5km)을 넘으면 NULL(역세권/초품아 아님)."""
    conn = db.connect(":memory:")
    cid = _seed_complex(conn, "11680", "역삼동", "외딴단지", 37.4000, 127.4000)
    _add_poi(conn, "subway", "강남", "2호선", 37.4979, 127.0276)   # 수십 km
    _add_poi(conn, "elem", "역삼초등학교", None, 37.4990, 127.0300)
    poi.compute_nearest(conn, refresh=True)
    r = conn.execute(
        "SELECT subway_m, subway_nm, school_m, poi_fetched_at FROM complex "
        "WHERE complex_id=?", (cid,)).fetchone()
    assert r["subway_m"] is None and r["subway_nm"] is None
    assert r["school_m"] is None
    assert r["poi_fetched_at"] is not None          # 계산은 됨(먼 것도 처리 기록)
    conn.close()


def test_incremental_skips_computed():
    """refresh=False 는 poi_fetched_at 있는 단지를 건너뛴다(증분)."""
    conn = db.connect(":memory:")
    c1 = _seed_complex(conn, "11680", "역삼동", "단지1", 37.4979, 127.0276)
    _add_poi(conn, "subway", "강남", "2호선", 37.4979, 127.0276)
    poi.compute_nearest(conn, refresh=True)         # c1 계산됨
    # 신규 단지 추가 → 증분은 신규만
    c2 = _seed_complex(conn, "11680", "역삼동", "단지2", 37.4990, 127.0290)
    out = poi.compute_nearest(conn, refresh=False)
    assert out["updated"] == 1                      # c2만
    assert conn.execute(
        "SELECT subway_m FROM complex WHERE complex_id=?", (c2,)).fetchone()[0] is not None
    conn.close()


def test_no_poi_returns_flag():
    conn = db.connect(":memory:")
    _seed_complex(conn, "11680", "역삼동", "단지", 37.4979, 127.0276)
    out = poi.compute_nearest(conn, refresh=True)
    assert out.get("no_poi") is True
    conn.close()
