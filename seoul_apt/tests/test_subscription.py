"""청약·분양 수집/알림 단위테스트 (네트워크 없이 raw dict fixture 사용)."""

from datetime import date, timedelta

from seoul_apt import db, export, notify
from seoul_apt.subscription import (_parse_notice, _parse_model, _parse_cmpet,
                                    extract_gu)

RAW_NOTICE = {
    "HOUSE_MANAGE_NO": 2026000123,
    "PBLANC_NO": "2026000123",
    "HOUSE_NM": "서초 그랑자이 2차",
    "HSSPLY_ADRES": "서울특별시 서초구 반포동 123-4",
    "TOT_SUPLY_HSHLDCO": "350",
    "RCRIT_PBLANC_DE": "2026-06-20",
    "RCEPT_BGNDE": "2026-07-10",
    "RCEPT_ENDDE": "2026-07-12",
    "PRZWNER_PRESNATN_DE": "2026-07-18",
    "CNTRCT_CNCLS_BGNDE": "2026-08-01",
    "CNTRCT_CNCLS_ENDDE": "2026-08-03",
    "MVN_PREARNGE_YM": "202812",
    "CNSTRCT_ENTRPS_NM": "GS건설",
    "PBLANC_URL": "https://www.applyhome.co.kr/x/123",
}
RAW_MODEL = {
    "HOUSE_MANAGE_NO": "2026000123", "MODEL_NO": "01",
    "HOUSE_TY": "084.9700A", "SUPLY_AR": "112.4",
    "SUPLY_HSHLDCO": "120", "SPSPLY_HSHLDCO": "80",
    "LTTOT_TOP_AMOUNT": "215,000",
}
RAW_CMPET = {
    "HOUSE_MANAGE_NO": "2026000123", "HOUSE_TY": "084.9700A",
    "RESIDE_SENM": "해당지역", "SUBSCRPT_RANK_CODE": 1,
    "REQ_CNT": "3,120", "CMPET_RATE": "26.0",
}


def test_extract_gu():
    assert extract_gu("서울특별시 서초구 반포동 123-4") == "서초구"
    assert extract_gu("서울 강남구 대치동 316") == "강남구"
    assert extract_gu(None) is None
    assert extract_gu("경기도 성남시 분당구") is None   # 서울 아님


def test_optn_yyyymmdd_dates_normalized():
    """임의공급은 날짜를 'YYYYMMDD'로 준다 - 저장 전 'YYYY-MM-DD'로 통일해야 한다.

    통일하지 않으면 '20260108' > '2026-07-23' ('0' > '-')이라 지난 임의공급
    공고가 전부 '예정'으로 표시된다(실제 18건 오노출).
    """
    n = _parse_notice({
        "HOUSE_MANAGE_NO": "opt1", "HOUSE_NM": "임의공급 단지",
        "HOUSE_SECD_NM": "임의공급",
        "RCRIT_PBLANC_DE": "20260105", "RCEPT_BGNDE": "20260108",
        "RCEPT_ENDDE": "20260109", "PRZWNER_PRESNATN_DE": "20260115",
    }, "optn")
    assert n["rcrit_de"] == "2026-01-05"
    assert n["rcept_bgnde"] == "2026-01-08"
    assert n["rcept_endde"] == "2026-01-09"
    assert n["przwner_de"] == "2026-01-15"
    # 정규화 후에는 지난 공고로 올바르게 비교된다(‘예정’ 오판 방지)
    assert n["rcept_endde"] < "2026-07-23"
    # 이미 하이픈 포맷(APT·무순위)은 그대로 통과
    assert _parse_notice(RAW_NOTICE, "apt")["rcept_bgnde"] == "2026-07-10"


def test_parse_and_upsert_updates_schedule():
    conn = db.connect(":memory:")
    n = _parse_notice(RAW_NOTICE, "apt")
    assert n["house_manage_no"] == "2026000123"   # 숫자여도 문자열화
    assert n["tot_suply"] == 350
    n["fetched_at"] = "t1"
    db.upsert_subscription(conn, n)

    # 접수일 연기 재수집 → 갱신되어야 함(ON CONFLICT DO UPDATE)
    n2 = _parse_notice({**RAW_NOTICE, "RCEPT_BGNDE": "2026-07-24",
                        "RCEPT_ENDDE": "2026-07-26"}, "apt")
    n2["fetched_at"] = "t2"
    db.upsert_subscription(conn, n2)
    row = conn.execute("SELECT * FROM subscription").fetchone()
    assert row["rcept_bgnde"] == "2026-07-24"
    assert row["fetched_at"] == "t2"
    assert conn.execute("SELECT COUNT(*) FROM subscription").fetchone()[0] == 1
    conn.close()


def test_models_cmpet_and_export_items():
    conn = db.connect(":memory:")
    n = _parse_notice(RAW_NOTICE, "apt")
    n["fetched_at"] = "t"
    db.upsert_subscription(conn, n)
    db.upsert_subscription_model(conn, _parse_model(RAW_MODEL, "2026000123"))
    db.upsert_subscription_cmpet(conn, _parse_cmpet(RAW_CMPET, "2026000123"))
    conn.commit()

    items = export.subscription_items(conn, "2026-07-06")
    assert len(items) == 1
    it = items[0]
    assert it["gu"] == "서초구"
    assert it["models"] == [{"ty": "084.9700A", "ar": 112.4, "hh": 120,
                             "shh": 80, "price": 215000}]
    assert it["cmpet"][0]["rate"] == "26.0"
    assert it["cmpet"][0]["resd"] == "해당지역 1순위"   # 순위 병기(덮어쓰기 방지)
    # 1년 넘게 지난 마감 공고는 제외
    old = _parse_notice({**RAW_NOTICE, "HOUSE_MANAGE_NO": "9",
                         "RCEPT_ENDDE": "2024-01-05"}, "apt")
    old["fetched_at"] = "t"
    db.upsert_subscription(conn, old)
    assert len(export.subscription_items(conn, "2026-07-06")) == 1
    conn.close()


def test_safety_margin_in_export():
    """분양가 vs 반경 내 같은 평형 실거래 → 안전마진(mgn) 산출."""
    conn = db.connect(":memory:")
    # 분양 공고(강남 좌표) 84형 분양가 10억
    n = _parse_notice({**RAW_NOTICE, "HSSPLY_ADRES": "서울특별시 강남구 대치동 1"},
                      "apt")
    n["lat"], n["lon"] = 37.4990, 127.0620
    n["fetched_at"] = "t"
    conn.execute("INSERT INTO subscription (house_manage_no,kind,house_nm,adres,"
                 "rcept_endde,lat,lon,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                 (n["house_manage_no"], "apt", n["house_nm"], n["adres"],
                  "2026-07-20", n["lat"], n["lon"], "t"))
    db.upsert_subscription_model(conn, _parse_model(
        {"HOUSE_MANAGE_NO": n["house_manage_no"], "HOUSE_TY": "084.9700A",
         "SUPLY_AR": "112.4", "SUPLY_HSHLDCO": "100",
         "LTTOT_TOP_AMOUNT": "100000"}, n["house_manage_no"]))
    # 주변 단지(같은 좌표 인근) 84㎡ 최근 실거래 12억×3건 → 마진 +16.7%
    from datetime import date
    cid = db.upsert_complex(conn, "11680", "대치동", "인근아파트", 2015, "2")
    db.set_coords(conn, cid, 37.4992, 127.0622, "t")
    for i in range(3):
        db.insert_sale(conn, cid, date.today().isoformat(), 84.5, 10 + i, 120000)
    conn.commit()

    items = export.subscription_items(conn, date.today().isoformat())
    m = items[0]["models"][0]
    assert m["mkt"] == 120000 and m["mkt_n"] == 3
    assert m["mgn"] == round((120000 - 100000) / 120000 * 100, 1)   # +16.7%
    conn.close()


def test_subscription_news_known_and_today_start():
    conn = db.connect(":memory:")
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=10)).isoformat()
    # 공고 A: 신규(모름) / 공고 B: 이미 알고 있고 오늘 접수 시작
    a = _parse_notice({**RAW_NOTICE, "HOUSE_MANAGE_NO": "A",
                       "RCEPT_BGNDE": future, "RCEPT_ENDDE": future}, "apt")
    b = _parse_notice({**RAW_NOTICE, "HOUSE_MANAGE_NO": "B",
                       "HOUSE_NM": "마포 어반포레",
                       "HSSPLY_ADRES": "서울특별시 마포구 아현동 1",
                       "RCEPT_BGNDE": today, "RCEPT_ENDDE": future}, "remndr")
    for n in (a, b):
        n["fetched_at"] = "t"
        db.upsert_subscription(conn, n)
    conn.commit()

    lines, new_ids = notify.subscription_news(
        conn, known_ids={"B"}, today=today, watch_gus={"마포구"})
    text = "\n".join(lines)
    assert new_ids == {"A"}
    assert "신규 분양공고" in text and "서초 그랑자이" in text
    assert "오늘 청약접수 시작" in text and "마포 어반포레" in text
    assert "⭐ 마포구" in text          # 워치리스트 구 강조
    assert "(무순위)" in text
    conn.close()
