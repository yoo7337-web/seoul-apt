"""청약홈 웹 캘린더 보조수집 단위테스트 (네트워크 없이 응답 fixture 사용)."""

from datetime import date

from seoul_apt import db
from seoul_apt.applyhome_web import notices_from_calendar, months_to_check

# 실제 응답 모양(2026-07 서울). 한 공고가 특별→1순위→2순위로 여러 날에 걸쳐 나온다.
ROWS = [
    {"HOUSE_NM": "월계 중흥S-클래스 리비에르", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260727", "RCEPT_SE": "01", "RESTDE_AT": "N",
     "PBLANC_NO": 2026000355, "HOUSE_MANAGE_NO": 2026000355},
    {"HOUSE_NM": "월계 중흥S-클래스 리비에르", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260728", "RCEPT_SE": "02", "RESTDE_AT": "N",
     "PBLANC_NO": 2026000355, "HOUSE_MANAGE_NO": 2026000355},
    {"HOUSE_NM": "월계 중흥S-클래스 리비에르", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260730", "RCEPT_SE": "03", "RESTDE_AT": "N",
     "PBLANC_NO": 2026000355, "HOUSE_MANAGE_NO": 2026000355},
    {"HOUSE_NM": "해링턴 플레이스 노원 센트럴", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260727", "RCEPT_SE": "11", "RESTDE_AT": "N",
     "PBLANC_NO": 2026940157, "HOUSE_MANAGE_NO": 2026940157},
    {"HOUSE_NM": "아크로 리버스카이", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260728", "RCEPT_SE": "06", "RESTDE_AT": "N",
     "PBLANC_NO": 2026910194, "HOUSE_MANAGE_NO": 2026910194},
    {"HOUSE_NM": "e편한세상 강동 프레스티지원", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260727", "RCEPT_SE": "07", "RESTDE_AT": "N",
     "PBLANC_NO": 2026930024, "HOUSE_MANAGE_NO": 2026930024},
    # 수집 범위 밖(공공지원민간임대 04 · 오피스텔등 05)은 제외돼야 한다
    {"HOUSE_NM": "어떤 민간임대", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260727", "RCEPT_SE": "04", "RESTDE_AT": "N",
     "PBLANC_NO": 1, "HOUSE_MANAGE_NO": 1},
    {"HOUSE_NM": "어떤 오피스텔", "SUBSCRPT_AREA_CODE_NM": "서울",
     "IN_DATE": "20260727", "RCEPT_SE": "05", "RESTDE_AT": "N",
     "PBLANC_NO": 2, "HOUSE_MANAGE_NO": 2},
]


def _by_name(items):
    return {i["house_nm"]: i for i in items}


def test_groups_multi_day_notice_into_one_period():
    """특별→1순위→2순위로 흩어진 행을 한 공고의 접수기간으로 묶는다."""
    got = _by_name(notices_from_calendar(ROWS))
    w = got["월계 중흥S-클래스 리비에르"]
    assert w["rcept_bgnde"] == "2026-07-27"    # 특별공급일
    assert w["rcept_endde"] == "2026-07-30"    # 2순위일
    assert (w["kind"], w["secd_nm"]) == ("apt", "일반공급")
    assert w["house_manage_no"] == "2026000355"


def test_supply_type_mapping_and_scope():
    got = _by_name(notices_from_calendar(ROWS))
    assert (got["해링턴 플레이스 노원 센트럴"]["kind"],
            got["해링턴 플레이스 노원 센트럴"]["secd_nm"]) == ("optn", "임의공급")
    assert (got["아크로 리버스카이"]["kind"],
            got["아크로 리버스카이"]["secd_nm"]) == ("remndr", "무순위")
    assert (got["e편한세상 강동 프레스티지원"]["kind"],
            got["e편한세상 강동 프레스티지원"]["secd_nm"]) == ("remndr", "불법행위 재공급")
    # 공공지원민간임대·오피스텔등은 API 수집 범위 밖이라 제외
    assert "어떤 민간임대" not in got and "어떤 오피스텔" not in got


def test_holiday_rows_and_bad_dates_ignored():
    rows = [
        {"HOUSE_NM": "제헌절", "SUBSCRPT_AREA_CODE_NM": "서울", "IN_DATE": "20260717",
         "RCEPT_SE": "01", "RESTDE_AT": "Y", "HOUSE_MANAGE_NO": 9, "PBLANC_NO": 9},
        {"HOUSE_NM": "날짜이상", "SUBSCRPT_AREA_CODE_NM": "서울", "IN_DATE": "2026-07",
         "RCEPT_SE": "01", "RESTDE_AT": "N", "HOUSE_MANAGE_NO": 8, "PBLANC_NO": 8},
    ]
    # 휴일행은 fetch_calendar 에서 걸러지지만, 파서도 깨진 날짜를 흘리면 안 된다
    assert notices_from_calendar([rows[1]]) == []


def test_web_notice_does_not_clobber_api_row():
    """API 로 이미 받은 공고는 웹 보조가 덮어쓰지 않는다(일정만 있어 손해)."""
    conn = db.connect(":memory:")
    api = {
        "house_manage_no": "2026000355", "pblanc_no": "2026000355", "kind": "apt",
        "secd_nm": "일반공급", "house_nm": "월계 중흥S-클래스 리비에르",
        "adres": "서울특별시 노원구 월계동 487-17", "tot_suply": 135,
        "rcrit_de": "2026-07-16", "rcept_bgnde": "2026-07-27",
        "rcept_endde": "2026-07-30", "przwner_de": "2026-08-05",
        "cntrct_bgnde": None, "cntrct_endde": None, "mvn_ym": "202808",
        "cnstrct_nm": "중흥토건", "url": "https://x", "fetched_at": "t",
    }
    db.upsert_subscription(conn, api)
    conn.commit()
    assert db.subscription_exists(conn, "2026000355") is True

    # supplement 는 존재하는 공고를 건너뛴다 - 그 규칙대로면 주소가 살아있어야 한다
    for n in notices_from_calendar(ROWS):
        if db.subscription_exists(conn, n["house_manage_no"]):
            continue
        n["fetched_at"] = "t2"
        db.upsert_subscription(conn, n, src="web")
    conn.commit()

    row = conn.execute("SELECT * FROM subscription WHERE house_manage_no='2026000355'").fetchone()
    assert row["adres"] == "서울특별시 노원구 월계동 487-17"   # API 값 보존
    assert row["src"] == "api"
    # 웹에만 있던 공고는 새로 들어오고 src='web'
    new = conn.execute("SELECT * FROM subscription WHERE house_manage_no='2026940157'").fetchone()
    assert new["house_nm"] == "해링턴 플레이스 노원 센트럴"
    assert new["src"] == "web" and new["adres"] is None
    conn.close()


def test_months_to_check_includes_next_month():
    assert months_to_check(date(2026, 7, 23)) == ["202607", "202608"]
    assert months_to_check(date(2026, 12, 5)) == ["202612", "202701"]
