"""한국부동산원 R-ONE 부동산통계 OpenAPI 클라이언트(지역 단위 시세/지수).

R-ONE OpenAPI: https://www.reb.or.kr/r-one/openapi/SttsApiTbl.do
  파라미터 KEY, STATBL_ID, DTACYCLE_CD(MM 등), Type=json,
           START_WRTTIME/END_WRTTIME(YYYYMM), pIndex, pSize
전국주택가격동향조사(월간) 아파트 매매/전세 가격지수를 서울/자치구 단위로 적재한다.
지역 단위 보조지표이므로 실패해도 전체 파이프라인을 막지 않는다(best-effort).

주의: STATBL_ID 는 R-ONE '통계표 목록'에서 확인해 필요 시 조정한다.
아래 값은 전국주택가격동향조사 월간 아파트 지수를 가리키는 대표값이며,
운영 중 응답이 비면 REB_STATS 를 R-ONE 목록 기준으로 갱신하면 된다.
"""

import time

import requests

from . import config, db

# 통계표 '데이터' 조회 엔드포인트(SttsApiTblData). SttsApiTbl 은 표 메타(목록)만 반환한다.
BASE = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"

# (STATBL_ID, 지표명, 수집주기) - 필요 시 R-ONE 통계표 목록 기준으로 수정
# CLS_FULLNM 이 지역('서울>...')인 표준형 통계들.
REB_STATS = [
    ("A_2024_00178", "아파트 매매가격지수", "MM"),  # (월) 지역별 매매지수_아파트
    ("A_2024_00182", "아파트 전세가격지수", "MM"),  # (월) 지역별 전세지수_아파트
    ("A_2024_00076", "아파트 매매수급지수", "MM"),  # (월) 매매수급동향_아파트(권역, 100↑=매수우위)
    ("T237973129847263", "미분양(호)", "MM"),       # 미분양주택현황(서울>구, '서울>계'=합계)
]

# 매입자거주지별 아파트매매(GRP_FULLNM=지역, CLS_FULLNM=거주지구분)
# → 외지인 비중(%) = (합계 - 관할시군구내 - 관할시도내) / 합계
BUYER_STATBL = "A_2024_00609"
BUYER_STAT_NAME = "외지인 매수비중(%)"


class RebAPIError(Exception):
    pass


class RebClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def fetch_stat(self, statbl_id: str, cycle: str,
                   start_ym: str, end_ym: str) -> list[dict]:
        """단일 통계표를 기간 조회해 원시 row 목록 반환."""
        rows: list[dict] = []
        page = 1
        while True:
            params = {
                "KEY": self.api_key,
                "STATBL_ID": statbl_id,
                "DTACYCLE_CD": cycle,
                "Type": "json",
                "pIndex": page,
                "pSize": 1000,
                "START_WRTTIME": start_ym,
                "END_WRTTIME": end_ym,
            }
            data = self._get_json(params)
            batch = _extract_rows(data)
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 1000:
                break
            page += 1
            time.sleep(config.REQUEST_SLEEP)
        return rows

    def _get_json(self, params: dict) -> dict:
        last_err = None
        for attempt in range(config.MAX_RETRY):
            try:
                resp = self.session.get(BASE, params=params,
                                        timeout=config.REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RebAPIError(f"R-ONE 요청 실패: {last_err}")


def _extract_rows(data: dict) -> list[dict]:
    """R-ONE 응답의 중첩 구조에서 row 리스트를 추출(포맷 관대 처리)."""
    if not isinstance(data, dict):
        return []
    for key, val in data.items():
        if isinstance(val, list):
            for part in val:
                if isinstance(part, dict) and "row" in part:
                    return part["row"] or []
    return []


def _period(row: dict) -> str | None:
    wt = str(row.get("WRTTIME_IDTFR_ID") or row.get("WRTTIME_DESC") or "").strip()
    if len(wt) >= 6 and wt[:6].isdigit():
        return f"{wt[:4]}-{wt[4:6]}"
    return None


def _region(row: dict) -> str:
    # CLS_FULLNM 은 '서울>도심권' 처럼 상위 지역을 포함하므로 서울 필터에 유리하다.
    for k in ("CLS_FULLNM", "CLS_NM", "C1_NM", "REGION_NM"):
        v = row.get(k)
        if v:
            return str(v).strip()
    return "서울"


def _stat_start(conn, stat_name: str, default_ym: str) -> str:
    """증분 시작 시점 - 이미 적재된 최신 period 2개월 전(정정 반영), 없으면 default.

    매입자거주지별처럼 전국 row 가 많은 통계를 매일 전 기간 재수집하지 않기 위함.
    """
    row = conn.execute(
        "SELECT MAX(period) AS p FROM reb_index WHERE stat_name=?",
        (stat_name,)).fetchone()
    if not row or not row["p"]:
        return default_ym
    y, m = int(row["p"][:4]), int(row["p"][5:7])
    m -= 2
    if m < 1:
        y, m = y - 1, m + 12
    ym = f"{y:04d}{m:02d}"
    return max(default_ym, ym) if default_ym else ym


def _buyer_outsider_rows(rows: list[dict]) -> list[tuple[str, str, float]]:
    """매입자거주지별 원시 row → (지역, period, 외지인비중%) 목록.

    GRP_FULLNM='서울>강남구'(지역), CLS_FULLNM='합계|관할시군구내|관할시도내|
    관할시도외_*'(매입자 거주지, 서로 배타적). 외지인 = 시도외 = 합계-시군구내-시도내.
    서울 전체는 '서울>계' 같은 집계행이 '계'로 다른 시도와 충돌하므로 쓰지 않고
    25개 구 합산으로 계산한다. 표본 10건 미만 월은 노이즈 커 제외.
    """
    gu_names = set(config.SEOUL_DISTRICTS.values())
    piv: dict[tuple, dict] = {}
    for r in rows:
        grp = str(r.get("GRP_FULLNM") or "")
        gu = str(r.get("GRP_NM") or "")
        if not grp.startswith("서울") or gu not in gu_names:
            continue
        period = _period(r)
        if not period:
            continue
        cls = str(r.get("CLS_FULLNM") or r.get("CLS_NM") or "")
        try:
            val = float(str(r.get("DTA_VAL")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        for key in ((gu, period), ("서울", period)):   # 구 + 서울(구 합산)
            d = piv.setdefault(key, {"total": 0, "intra": 0})
            if cls == "합계":
                d["total"] += val
            elif cls in ("관할시군구내", "관할시도내"):
                d["intra"] += val
    out = []
    for (region, period), d in piv.items():
        if d["total"] < 10:
            continue
        out.append((region, period,
                    round((d["total"] - d["intra"]) / d["total"] * 100, 1)))
    return out


def collect_reb(conn, api_key: str, start_ym: str, end_ym: str,
                force_start: bool = False) -> int:
    """설정된 통계표를 수집해 reb_index 에 적재. 적재 row 수 반환.

    기본은 증분(_stat_start: DB 최신 period 2개월 전부터). force_start=True 면
    start_ym 을 그대로 써서 과거 구간도 재수집한다 — 안 그러면 사용자가
    `--from 202001` 로 과거를 지정해도 DB에 최신값이 있어 조용히 무시됐다.
    """
    client = RebClient(api_key)
    n = 0
    for statbl_id, stat_name, cycle in REB_STATS:
        try:
            begin = start_ym if force_start else _stat_start(conn, stat_name, start_ym)
            rows = client.fetch_stat(statbl_id, cycle, begin, end_ym)
        except RebAPIError:
            continue
        for r in rows:
            region = _region(r)
            # 서울만 저장. CLS_FULLNM 은 '서울>...' 계층형이라 startswith 로 판별
            # (부분일치는 '인천>중구'가 '중구'에 걸려 타시도가 섞이는 버그가 있었음)
            if not region.startswith("서울"):
                continue
            period = _period(r)
            val = r.get("DTA_VAL") or r.get("value")
            if not period or val in (None, ""):
                continue
            try:
                value = float(str(val).replace(",", ""))
            except ValueError:
                continue
            db.insert_reb(conn, region, stat_name, period, value)
            n += 1
        conn.commit()

    # 외지인 매수비중(파생 지표 - pivot 계산 후 적재)
    try:
        rows = client.fetch_stat(BUYER_STATBL, "MM",
                                 _stat_start(conn, BUYER_STAT_NAME, start_ym),
                                 end_ym)
        for region, period, pct in _buyer_outsider_rows(rows):
            db.insert_reb(conn, region, BUYER_STAT_NAME, period, pct)
            n += 1
        conn.commit()
    except RebAPIError:
        pass
    return n
