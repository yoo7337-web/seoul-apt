"""notify(관심지역 알림)·reco(후보 선별) 단위테스트 - 네트워크 없음."""

import json

from seoul_apt import db, notify, reco


def _seed(conn):
    """대치동 은마 + 아현동 마포래미안 표본 데이터."""
    eunma = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    mapo = db.upsert_complex(conn, "11440", "아현동", "마포래미안푸르지오", 2014, "777")
    # 은마: 4월 5건(평단 낮음) → 5월 6건(평단 급등) → 신규 신고가 1건
    for i in range(5):
        db.insert_sale(conn, eunma, f"2026-04-{10+i:02d}", 76.79, 3 + i, 240000 + i * 1000)
    for i in range(5):
        db.insert_sale(conn, eunma, f"2026-05-{10+i:02d}", 76.79, 3 + i, 270000 + i * 1000)
    db.insert_sale(conn, eunma, "2026-05-20", 76.79, 15, 300000)      # 신고가
    db.insert_rent(conn, eunma, "2026-05-02", 76.79, 5, 180000, 0)    # 전세
    db.insert_sale(conn, mapo, "2026-05-21", 84.9, 10, 190000)
    conn.commit()
    return eunma, mapo


def test_match_watch():
    row = {"lawd_cd": "11680", "umd_nm": "대치동", "apt_nm": "은마"}
    assert notify.match_watch(row, {"lawd_cd": "11680"})
    assert notify.match_watch(row, {"lawd_cd": "11680", "umd": ["대치동"]})
    assert not notify.match_watch(row, {"lawd_cd": "11680", "umd": ["삼성동"]})
    assert notify.match_watch(row, {"lawd_cd": "11680", "apt_pattern": "은마"})
    assert not notify.match_watch(row, {"lawd_cd": "11680", "apt_pattern": "래미안"})
    assert not notify.match_watch(row, {"lawd_cd": "11440"})


def test_new_sales_and_peak_detection():
    conn = db.connect(":memory:")
    _seed(conn)
    rows = notify.new_sales(conn, 0)
    assert len(rows) == 12
    peaks = [r for r in rows if notify.is_new_peak(conn, r)]
    assert [p["amount_manwon"] for p in peaks] == [300000]
    # since_id 이후만
    assert notify.new_sales(conn, rows[-1]["id"]) == []
    conn.close()


def test_watched_complex_section():
    """⭐ 관심단지(complexes) 거래가 다이제스트 최상단 섹션으로 표시된다."""
    conn = db.connect(":memory:")
    eunma, mapo = _seed(conn)
    wl = {
        "watches": [], "complexes": [{"id": eunma, "apt": "은마", "lawd_cd": "11680"}],
        "swing_threshold_pct": 5, "swing_min_sample": 5, "digest_peak_limit": 5,
    }
    rows = notify.new_sales(conn, 0)
    msg = notify.build_message(conn, wl, rows)
    assert "⭐" in msg and "관심단지 거래" in msg
    assert msg.index("관심단지 거래") < msg.index("신규 수집 거래")   # 최상단
    assert "은마" in msg
    # 마포는 관심단지가 아니므로 ⭐ 섹션 안에 없어야 함(섹션 텍스트만 검사)
    star_sec = msg.split("신규 수집 거래")[0]
    assert "마포래미안푸르지오" not in star_sec
    # 관심단지 미등록이면 섹션 없음
    wl2 = dict(wl, complexes=[])
    assert "관심단지 거래" not in notify.build_message(conn, wl2, rows)
    conn.close()


def test_is_new_peak_matched_by_size():
    """신고가 알림 판정도 비슷한 크기(±12%)끼리 비교 - 대형 평형 역대가에
    소형 평형 신고가 알림이 가려지면 안 된다(사고 이력 회귀 테스트)."""
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    db.insert_sale(conn, cid, "2020-01-10", 135.0, 10, 200000)  # 대형 역대 20억
    db.insert_sale(conn, cid, "2021-01-10", 59.0, 3, 80000)     # 소형 과거 8억
    db.insert_sale(conn, cid, "2026-06-01", 59.0, 5, 90000)     # 소형 신고가 9억
    conn.commit()
    rows = notify.new_sales(conn, 0)
    new_row = next(r for r in rows if r["amount_manwon"] == 90000)
    assert notify.is_new_peak(conn, new_row) is True   # 20억에 가려지면 안 됨
    conn.close()


def test_watch_swing_detects_jump():
    conn = db.connect(":memory:")
    _seed(conn)
    watch = {"lawd_cd": "11680", "umd": ["대치동"]}
    sw = notify.watch_swing(conn, watch, threshold_pct=5, min_sample=5)
    assert sw is not None
    assert sw["prev_month"] == "2026-04" and sw["cur_month"] == "2026-05"
    assert sw["pct"] > 5
    # 표본 기준을 올리면(월 20건) 판정 불가
    assert notify.watch_swing(conn, watch, 5, 20) is None
    conn.close()


def test_build_message_sections():
    conn = db.connect(":memory:")
    _seed(conn)
    wl = {"watches": [
        {"name": "대치동", "lawd_cd": "11680", "umd": ["대치동"],
         "alerts": ["new_deal", "new_peak", "swing"]},
    ], "swing_threshold_pct": 5, "swing_min_sample": 5, "digest_peak_limit": 5}
    rows = notify.new_sales(conn, 0)
    msg = notify.build_message(conn, wl, rows)
    assert "일일 다이제스트" in msg
    assert "신규 수집 거래: <b>12건</b>" in msg
    assert "신규 신고가" in msg and "은마" in msg
    assert "대치동" in msg and "평단가 급변동" in msg
    conn.close()


def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    assert notify.load_state(p) == {"last_sale_id": 0}
    notify.save_state({"last_sale_id": 42}, p)
    assert notify.load_state(p)["last_sale_id"] == 42


def test_first_run_baseline(tmp_path, monkeypatch):
    """첫 실행에서 누적 전체가 신규로 잡히면 알림 없이 베이스라인만 저장."""
    conn = db.connect(":memory:")
    eunma = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    for i in range(10):
        db.insert_sale(conn, eunma, f"2026-05-{i+1:02d}", 76.79, 3, 250000 + i)
    conn.commit()
    state_p = tmp_path / "state.json"
    monkeypatch.setattr(notify.config, "NOTIFY_STATE_PATH", state_p)
    monkeypatch.setattr(notify, "FIRST_RUN_LIMIT", 5)  # 테스트용 낮은 문턱
    stats = notify.run_alerts(conn, dry_run=False)
    assert stats["sent"] is False
    assert notify.load_state(state_p)["last_sale_id"] == 10  # 베이스라인 저장
    # 두 번째 실행: 신규 1건 → 정상 감지 경로
    db.insert_sale(conn, eunma, "2026-05-20", 76.79, 9, 260000)
    conn.commit()
    rows = notify.new_sales(conn, notify.load_state(state_p)["last_sale_id"])
    assert len(rows) == 1 and rows[0]["amount_manwon"] == 260000
    conn.close()


def test_reco_matched_by_size(tmp_path):
    """추천 후보의 평단가·전세가율은 비슷한 크기(±12%)로 계산 - 대형 평형이
    섞여 소형 평형 저평가 판정이 왜곡되면 안 된다(사고 이력 회귀 테스트)."""
    conn = db.connect(":memory:")
    cid = db.upsert_complex(conn, "11680", "대치동", "은마", 1979, "316")
    from datetime import date, timedelta
    anchor = date.today()
    # 대형(135㎡) 평단가 매우 높음(㎡당 비쌈) - 5건, 표본 요건 충족용
    for i in range(5):
        d = (anchor - timedelta(days=200 + i)).isoformat()
        db.insert_sale(conn, cid, d, 135.0, 10 + i, 600000)
    # 소형(59㎡) 최근 거래 1건 - 소형끼리 비교하면 실제로는 비싼(고평가) 거래
    recent_d = (anchor - timedelta(days=1)).isoformat()
    db.insert_sale(conn, cid, recent_d, 59.0, 3, 95000)
    for i in range(4):
        d = (anchor - timedelta(days=100 + i)).isoformat()
        db.insert_sale(conn, cid, d, 59.0, 4 + i, 80000)   # 59㎡ 기준시세 8억
    conn.commit()
    out = tmp_path / "reco.json"
    reco.build_candidates(conn, path=out, lawd_cds=["11680"])
    payload = json.loads(out.read_text(encoding="utf-8"))
    deal = next((c for c in payload["candidates"] if c["amount_manwon"] == 95000), None)
    # 전 평형 혼합이면 대형(600000) 때문에 discount가 크게 음수(저평가로 오판)가
    # 되지만, 59㎡끼리 비교하면 8억 대비 9.5억은 고평가 → 후보(discount<=-5%)가 아니어야 함
    assert deal is None or deal["discount_pct"] > reco.MIN_DISCOUNT_PCT
    conn.close()


def test_reco_candidates(tmp_path):
    conn = db.connect(":memory:")
    eunma, _ = _seed(conn)
    # 1년 중앙값 대비 -10% 저가 거래 추가(후보 조건 충족)
    db.insert_sale(conn, eunma, "2026-05-25", 76.79, 2, 243000)
    conn.commit()
    out = tmp_path / "reco.json"
    n = reco.build_candidates(conn, path=out, lawd_cds=["11680"])
    assert n >= 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["anchor_date"] == "2026-05-25"
    cheap = [c for c in payload["candidates"] if c["amount_manwon"] == 243000]
    assert cheap and cheap[0]["discount_pct"] <= -5
    assert cheap[0]["reasons"]
    # 점수 내림차순 정렬
    scores = [c["score"] for c in payload["candidates"]]
    assert scores == sorted(scores, reverse=True)
    conn.close()
