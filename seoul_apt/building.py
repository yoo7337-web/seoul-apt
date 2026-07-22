"""건축물대장(건축HUB) 기반 단지 부가정보 - 세대수·용적률·건폐율·사용승인일.

국토부 건축HUB '건축물대장정보 서비스'(같은 DATA_GO_KR_KEY, 활용신청 필요).
좌표가 이미 있는(=지오코딩된) 단지에 대해:
  1) 카카오 주소검색으로 b_code(법정동 10자리) + 지번(본번/부번) + 산여부를 얻고
  2) 총괄표제부(getBrRecapTitleInfo)로 단지 전체 세대수·용적률·건폐율·사용승인일을 조회.
     비어 있으면 표제부(getBrTitleInfo)로 폴백(동별 세대수 합, 용적률/건폐율 최댓값).
값이 0/공란인 항목(구건물 등 미기재)은 None 으로 저장한다.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests

from . import config, db

KST = timezone(timedelta(hours=9))
KAKAO_ADDR = "https://dapi.kakao.com/v2/local/search/address.json"
BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"
RECAP_EP = f"{BASE}/getBrRecapTitleInfo"   # 총괄표제부(단지 단위)
TITLE_EP = f"{BASE}/getBrTitleInfo"        # 표제부(동 단위)


def _int(v) -> int | None:
    try:
        n = int(float(str(v).replace(",", "").strip()))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _ratio(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return round(f, 2) if f > 0 else None
    except (TypeError, ValueError):
        return None


def _apr_date(v) -> str | None:
    """'20210730' → '2021-07-30'. 공란/이상값은 None."""
    s = str(v or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


class BuildingAPIError(Exception):
    """일시적 오류(네트워크·API 장애 등)로 조회를 완료하지 못함 - 재시도 대상.

    '요청 자체가 실패함'과 '요청은 성공했으나 매칭되는 주소/데이터가 없음'을
    구분해야 한다(사고 이력): 구분 없이 둘 다 None 으로 뭉치면
    collect_buildings 가 bldg_fetched_at 을 영구히 채워버려, 일시적 5xx가
    걸린 시간대에 처리된 단지는 실제로는 정보가 있는데도 다시는 재조회되지
    않는다.
    """


class BuildingClient:
    def __init__(self, data_key: str, kakao_key: str):
        self.data_key = data_key
        self.kakao_key = kakao_key
        self.session = requests.Session()

    # ── 주소 → 법정동코드/지번 ──────────────────────────────────────────
    def resolve(self, gu: str, umd: str | None, jibun: str | None) -> dict | None:
        """카카오 주소검색으로 (sigunguCd, bjdongCd, bun, ji, platGb) 반환.

        요청 자체가 끝내 실패하면 BuildingAPIError(재시도 대상). 요청은
        성공했는데 매칭 주소가 없으면 None(진짜 없음, 재조회 불필요).
        """
        parts = ["서울", gu]
        if umd:
            parts.append(umd)
        if jibun:
            parts.append(jibun)
        last_err = None
        for attempt in range(config.MAX_RETRY):
            try:
                r = self.session.get(
                    KAKAO_ADDR, headers={"Authorization": f"KakaoAK {self.kakao_key}"},
                    params={"query": " ".join(parts)}, timeout=config.REQUEST_TIMEOUT)
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                docs = r.json().get("documents") or []
                if not docs:
                    return None
                a = docs[0].get("address") or {}
                bcode = a.get("b_code") or ""
                if len(bcode) < 10:
                    return None
                return {
                    "sigunguCd": bcode[:5], "bjdongCd": bcode[5:10],
                    "bun": str(a.get("main_address_no") or "0").zfill(4),
                    "ji": str(a.get("sub_address_no") or "0").zfill(4),
                    "platGb": "1" if a.get("mountain_yn") == "Y" else "0",
                }
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise BuildingAPIError(f"카카오 주소검색 실패: {last_err}")

    def _get_items(self, endpoint: str, addr: dict) -> list[dict]:
        """요청 자체가 끝내 실패하면 BuildingAPIError(재시도 대상). 요청은
        성공했는데 이 엔드포인트에 데이터가 없으면 []( 폴백 경로로 계속 진행)."""
        params = {
            "serviceKey": self.data_key,
            "sigunguCd": addr["sigunguCd"], "bjdongCd": addr["bjdongCd"],
            "platGbCd": addr["platGb"], "bun": addr["bun"], "ji": addr["ji"],
            "_type": "json", "numOfRows": "50",
        }
        last_err = None
        for attempt in range(config.MAX_RETRY):
            try:
                r = self.session.get(endpoint, params=params,
                                     timeout=config.REQUEST_TIMEOUT)
                r.raise_for_status()
                body = (r.json().get("response") or {}).get("body") or {}
                items = body.get("items") or {}
                rows = items.get("item") if isinstance(items, dict) else items
                if rows is None:
                    return []
                return [rows] if isinstance(rows, dict) else list(rows)
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise BuildingAPIError(
            f"건축물대장 조회 실패({endpoint.rsplit('/', 1)[-1]}): {last_err}")

    def fetch(self, gu: str, umd: str | None, jibun: str | None) -> dict | None:
        """단지 부가정보 dict, 또는 None(주소가 진짜 매칭 안 됨).
        일시적 오류는 BuildingAPIError 로 전파한다(재시도 대상, 예외 삼키지 않음)."""
        addr = self.resolve(gu, umd, jibun)
        if not addr:
            return None

        recap = self._get_items(RECAP_EP, addr)
        result = {"households": None, "far": None, "bcr": None, "approval_date": None}
        if recap:
            it = recap[0]
            result["households"] = _int(it.get("hhldCnt"))
            result["far"] = _ratio(it.get("vlRat"))
            result["bcr"] = _ratio(it.get("bcRat"))
            result["approval_date"] = _apr_date(it.get("useAprDay"))

        # 총괄표제부에서 못 채운 값은 표제부(동별)로 폴백
        if not all([result["households"], result["far"], result["bcr"]]):
            titles = self._get_items(TITLE_EP, addr)
            if titles:
                hh = sum(_int(t.get("hhldCnt")) or 0 for t in titles)
                fars = [_ratio(t.get("vlRat")) for t in titles]
                bcrs = [_ratio(t.get("bcRat")) for t in titles]
                aprs = [_apr_date(t.get("useAprDay")) for t in titles]
                result["households"] = result["households"] or (hh or None)
                result["far"] = result["far"] or max([f for f in fars if f], default=None)
                result["bcr"] = result["bcr"] or max([b for b in bcrs if b], default=None)
                result["approval_date"] = result["approval_date"] or \
                    min([a for a in aprs if a], default=None)

        if not any(result.values()):
            return None
        return result


def collect_buildings(conn, data_key: str, kakao_key: str,
                      lawd_cd: str | None = None, limit: int | None = None,
                      max_workers: int = 8) -> dict:
    """건축물대장 정보 없는 단지를 조회해 저장. 통계 dict 반환.

    단지당 카카오 주소검색 1회 + 정부API 1~2회를 순차 호출해 건당 약 1.6초가
    걸린다(실측) - 수천 건 단위에서는 이게 병목이라 **네트워크 조회는 스레드풀로
    병렬화**하고(각 단지 조회는 완전히 독립적), DB 기록만 메인 스레드에서 순차
    처리한다(SQLite 쓰기는 스레드 안전이 아님 + 커밋 순서를 단순하게 유지).
    """
    client = BuildingClient(data_key, kakao_key)
    targets = db.complexes_without_building(conn, lawd_cd, limit)
    stats = {"tried": 0, "filled": 0, "failed": 0}

    def _fetch(row):
        gu = config.SEOUL_DISTRICTS.get(row["lawd_cd"], "")
        try:
            return row, client.fetch(gu, row["umd_nm"], row["jibun"]), None
        except BuildingAPIError as e:
            return row, None, e

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch, row) for row in targets]
        for fut in as_completed(futures):
            row, info, err = fut.result()
            if err is not None:
                # 일시적 오류 - bldg_fetched_at 을 채우지 않아 다음 실행에 재시도됨
                print(f"[building] {row['apt_nm']} 실패(재시도 예정): {err}")
                stats["failed"] += 1
                continue
            now = datetime.now(KST).isoformat(timespec="seconds")
            if info:
                db.set_building(conn, row["complex_id"], info["households"],
                                info["far"], info["bcr"], info["approval_date"], now)
                stats["filled"] += 1
            else:
                # 조회는 성공했으나 매칭되는 주소/데이터가 없음 - 재조회 방지 위해 시각만 기록
                db.set_building(conn, row["complex_id"], None, None, None, None, now)
            # 느린 API 대기 중 쓰기 락을 쥐지 않도록 매 건 즉시 커밋
            conn.commit()
            stats["tried"] += 1
    return stats
