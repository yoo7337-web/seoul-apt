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
REB_STATS = [
    ("A_2024_00178", "아파트 매매가격지수", "MM"),  # (월) 지역별 매매지수_아파트
    ("A_2024_00182", "아파트 전세가격지수", "MM"),  # (월) 지역별 전세지수_아파트
]


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


def collect_reb(conn, api_key: str, start_ym: str, end_ym: str) -> int:
    """설정된 통계표를 수집해 reb_index 에 적재. 적재 row 수 반환."""
    client = RebClient(api_key)
    n = 0
    seoul_names = set(config.SEOUL_DISTRICTS.values()) | {"서울", "서울특별시"}
    for statbl_id, stat_name, cycle in REB_STATS:
        try:
            rows = client.fetch_stat(statbl_id, cycle, start_ym, end_ym)
        except RebAPIError:
            continue
        for r in rows:
            region = _region(r)
            # 서울/자치구 관련 지역만 저장
            if not any(s in region for s in seoul_names):
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
    return n
