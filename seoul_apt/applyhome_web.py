"""청약홈 웹 캘린더 보조 수집 (공공데이터 API 지연 보완).

공공데이터 API(ApplyhomeInfoDetailSvc)는 청약홈 웹보다 며칠 늦게 반영된다.
실제로 2026-07-23 기준 웹 캘린더에 있는 7/27 해링턴 플레이스 노원 센트럴(임의공급),
7/28 아크로 리버스카이(무순위)가 API엔 아직 없었다. 접수 임박 공고를 놓치면
쓸모가 없으므로, **API를 기본으로 두고 웹 캘린더를 보조로** 덧댄다.

엔드포인트(캘린더 화면이 쓰는 내부 AJAX):
  POST https://www.applyhome.co.kr/ai/aib/selectSubscrptCalender.do
  본문: {"reqData": {"inqirePd": "202607"}}     ← reqData 로 감싸야 한다
  헤더: gvPgmId: AIB01M01, ajaxAt: Y (없으면 {"exception":"System Error"})
  선행: 캘린더 뷰 페이지를 한 번 GET 해 세션 쿠키(AH_JSESSION_ID) 확보
응답 schdulList[]: {HOUSE_NM, SUBSCRPT_AREA_CODE_NM, IN_DATE('YYYYMMDD'),
  RCEPT_SE(접수구분), HOUSE_MANAGE_NO, PBLANC_NO, RESTDE_AT(휴일행 'Y')}

⚠ 한계: 캘린더는 **일정만** 준다. 주소·좌표·세대수·분양가·안전마진은 없다.
그래서 웹 출처 공고는 목록에 뜨되 상세는 비어 있고, API가 따라잡으면 그때
정식 데이터로 덮인다(upsert_subscription 이 src='api' 로 갱신).
"""

import time
from datetime import date

import requests

from . import config, db

BASE = "https://www.applyhome.co.kr"
VIEW_URL = f"{BASE}/ai/aib/selectSubscrptCalenderView.do"
CAL_URL = f"{BASE}/ai/aib/selectSubscrptCalender.do"
DETAIL_APT = f"{BASE}/ai/aia/selectAPTLttotPblancDetail.do"
DETAIL_REMNDR = f"{BASE}/ai/aia/selectAPTRemndrLttotPblancDetailView.do"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 접수구분(RCEPT_SE) → (kind, secd_nm). 화면 houseSeClass/mbHouseSeClass 매핑 기준.
# 공공지원민간임대(04)·오피스텔등(05)·민간사전청약(08~10)은 API 수집 범위 밖이라 제외.
RCEPT_SE = {
    "01": ("apt", "일반공급"),          # APT 특별공급
    "02": ("apt", "일반공급"),          # APT 1순위
    "03": ("apt", "일반공급"),          # APT 2순위
    "06": ("remndr", "무순위"),
    "07": ("remndr", "불법행위 재공급"),
    "11": ("optn", "임의공급"),
}
# 한 공고에 여러 접수구분이 섞이면 이 순서로 대표 유형을 고른다(구체적인 것 우선).
_KIND_PRIORITY = ["07", "11", "06", "01", "02", "03"]


class ApplyhomeWebError(Exception):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    s.get(VIEW_URL, timeout=config.REQUEST_TIMEOUT)   # 세션 쿠키 확보
    return s


def fetch_calendar(yyyymm: str, session: requests.Session | None = None,
                   area: str = "서울") -> list[dict]:
    """해당 월 캘린더의 일정 행(area 지역만). 실패 시 ApplyhomeWebError."""
    s = session or _session()
    try:
        r = s.post(CAL_URL, json={"reqData": {"inqirePd": yyyymm}},
                   headers={"Referer": VIEW_URL, "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                            "gvPgmId": "AIB01M01", "ajaxAt": "Y"},
                   timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json()
    except (requests.RequestException, ValueError) as e:
        raise ApplyhomeWebError(f"캘린더 조회 실패({yyyymm}): {e}") from e
    if j.get("exception"):
        raise ApplyhomeWebError(f"캘린더 응답 오류({yyyymm}): {j['exception']}")
    rows = j.get("schdulList") or []
    return [r for r in rows
            if r.get("SUBSCRPT_AREA_CODE_NM") == area and r.get("RESTDE_AT") != "Y"]


def notices_from_calendar(rows: list[dict]) -> list[dict]:
    """일정 행(공고×날짜)을 공고 단위로 묶어 subscription 레코드 모양으로.

    같은 공고가 특별공급·1순위·2순위처럼 여러 날에 걸쳐 나오므로 최소·최대
    날짜를 접수 시작·종료로 삼는다(월계 중흥: 7/27 특별~7/30 2순위 → 7/27~7/30).
    """
    grouped: dict[str, dict] = {}
    for r in rows:
        se = str(r.get("RCEPT_SE") or "").zfill(2)
        if se not in RCEPT_SE:
            continue
        hmn = str(r.get("HOUSE_MANAGE_NO") or "").strip()
        d = str(r.get("IN_DATE") or "").strip()
        if not hmn or len(d) != 8 or not d.isdigit():
            continue
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        g = grouped.setdefault(hmn, {
            "house_manage_no": hmn,
            "pblanc_no": str(r.get("PBLANC_NO") or "").strip() or None,
            "house_nm": (r.get("HOUSE_NM") or "").strip(),
            "ses": set(), "bgn": iso, "end": iso,
        })
        g["ses"].add(se)
        g["bgn"] = min(g["bgn"], iso)
        g["end"] = max(g["end"], iso)

    out = []
    for g in grouped.values():
        se = next(s for s in _KIND_PRIORITY if s in g["ses"])
        kind, secd = RCEPT_SE[se]
        detail = DETAIL_APT if kind == "apt" else DETAIL_REMNDR
        out.append({
            "house_manage_no": g["house_manage_no"],
            "pblanc_no": g["pblanc_no"],
            "kind": kind,
            "secd_nm": secd,
            "house_nm": g["house_nm"],
            "adres": None, "tot_suply": None, "rcrit_de": None,
            "rcept_bgnde": g["bgn"], "rcept_endde": g["end"],
            "przwner_de": None, "cntrct_bgnde": None, "cntrct_endde": None,
            "mvn_ym": None, "cnstrct_nm": None,
            "url": f"{detail}?houseManageNo={g['house_manage_no']}"
                   f"&pblancNo={g['pblanc_no'] or g['house_manage_no']}",
        })
    return out


def months_to_check(today: date | None = None) -> list[str]:
    """이번 달 + 다음 달(월말에 다음 달 초 공고를 놓치지 않도록)."""
    t = today or date.today()
    nxt = date(t.year + (t.month == 12), 1 if t.month == 12 else t.month + 1, 1)
    return [t.strftime("%Y%m"), nxt.strftime("%Y%m")]


def supplement(conn, today: date | None = None) -> dict:
    """API 에 아직 없는 공고만 웹 캘린더에서 채운다. 통계 dict 반환.

    이미 있는 공고는 건드리지 않는다(웹은 일정만 있어 API 데이터를 덮으면 손해).
    """
    stats = {"seen": 0, "added": 0, "months": []}
    now = None
    try:
        session = _session()
    except requests.RequestException as e:
        print(f"[applyhome_web] 세션 준비 실패 - 보조수집 건너뜀: {e}")
        return stats

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")

    for ym in months_to_check(today):
        try:
            rows = fetch_calendar(ym, session)
        except ApplyhomeWebError as e:
            print(f"[applyhome_web] {e}")
            continue
        stats["months"].append(ym)
        for n in notices_from_calendar(rows):
            stats["seen"] += 1
            if db.subscription_exists(conn, n["house_manage_no"]):
                continue
            n["fetched_at"] = now
            db.upsert_subscription(conn, n, src="web")
            stats["added"] += 1
        time.sleep(config.REQUEST_SLEEP)
    conn.commit()
    return stats
