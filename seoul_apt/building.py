"""건축물대장(건축HUB) 기반 단지 부가정보 - 세대수·용적률·건폐율·사용승인일.

국토부 건축HUB '건축물대장정보 서비스'(같은 DATA_GO_KR_KEY, 활용신청 필요).
좌표가 이미 있는(=지오코딩된) 단지에 대해:
  1) 카카오 주소검색으로 b_code(법정동 10자리) + 지번(본번/부번) + 산여부를 얻고
  2) 총괄표제부(getBrRecapTitleInfo)로 단지 전체 세대수·용적률·건폐율·사용승인일을 조회.
     비어 있으면 표제부(getBrTitleInfo)로 폴백(동별 세대수 합, 용적률/건폐율 최댓값).
값이 0/공란인 항목(구건물 등 미기재)은 None 으로 저장한다.
"""

import threading
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


def _park(it: dict) -> dict:
    """주차대수 4종 → {'total','indr','oudr'}.

    '지하주차장 유무' 항목은 건축물대장에 없다 - **옥내(indr) 주차대수>0** 을
    프록시로 쓴다(아파트에서 옥내 주차는 사실상 지하주차장). 0 은 '없음'이라는
    정보라 None(미기재)과 구분해야 하므로 _int(0→None) 대신 여기서 따로 센다.
    """
    def n(key):
        try:
            return max(0, int(float(str(it.get(key) or 0).replace(",", "").strip())))
        except (TypeError, ValueError):
            return 0
    indr = n("indrMechUtcnt") + n("indrAutoUtcnt")
    oudr = n("oudrMechUtcnt") + n("oudrAutoUtcnt")
    total = n("totPkngCnt") or (indr + oudr)
    if not total and not indr and not oudr:
        return {}                      # 주차 항목 자체가 미기재(구건물 등)
    if total and not indr and not oudr:
        # 총 대수만 있고 옥내/옥외 내역이 비어 있는 대장이 있다(실측: 극동 총18·내역0).
        # 이걸 indr=0 으로 저장하면 '지상주차만'으로 **단정**되어 필터에서 잘못
        # 걸러진다 - 내역은 '모름'(None)으로 두고 총 대수만 쓴다.
        return {"total": total, "indr": None, "oudr": None}
    return {"total": total or None, "indr": indr, "oudr": oudr}


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


# 건축물대장 API는 **키 단위 초당 요청 제한**이 있다(실측: 10스레드로 몰면 3건 중
# 1건이 429). 워커를 늘려도 429 재시도로 오히려 느려지므로, 스레드 수와 무관하게
# 전역 호출 간격을 강제한다. 0.2s ≈ 5 req/s - 순차 실측(5.7 req/s)에서 429 0건.
_GOV_MIN_INTERVAL = 0.2


class _RateLimiter:
    """스레드 공용 최소 호출 간격 보장(간단한 토큰버킷 대용)."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                delay = self._next - now
            else:
                delay = 0.0
            self._next = max(now, self._next) + self.interval
        if delay:
            time.sleep(delay)


class BuildingClient:
    def __init__(self, data_key: str, kakao_key: str):
        self.data_key = data_key
        self.kakao_key = kakao_key
        self.session = requests.Session()
        self.limiter = _RateLimiter(_GOV_MIN_INTERVAL)

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

    def _get_items(self, endpoint: str, addr: dict, rows: int = 50) -> list[dict]:
        """요청 자체가 끝내 실패하면 BuildingAPIError(재시도 대상). 요청은
        성공했는데 이 엔드포인트에 데이터가 없으면 []( 폴백 경로로 계속 진행).

        rows: 표제부는 동 수만큼 행이 온다 - 세대수 합산엔 전부 필요하지만
        **주차는 필지 단위 값이라 1행이면 충분**하다(대단지 응답이 수십 배 작아짐).
        """
        params = {
            "serviceKey": self.data_key,
            "sigunguCd": addr["sigunguCd"], "bjdongCd": addr["bjdongCd"],
            "platGbCd": addr["platGb"], "bun": addr["bun"], "ji": addr["ji"],
            "_type": "json", "numOfRows": str(rows),
        }
        last_err = None
        for attempt in range(config.MAX_RETRY):
            try:
                self.limiter.wait()
                r = self.session.get(endpoint, params=params,
                                     timeout=config.REQUEST_TIMEOUT)
                if r.status_code == 429:      # 제한 초과 - 간격을 늘려 재시도
                    time.sleep(1 + attempt * 2)
                    last_err = "429 Too Many Requests"
                    continue
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

    def fetch(self, gu: str, umd: str | None, jibun: str | None,
              park_only: bool = False) -> dict | None:
        """단지 부가정보 dict, 또는 None(주소가 진짜 매칭 안 됨).
        일시적 오류는 BuildingAPIError 로 전파한다(재시도 대상, 예외 삼키지 않음).

        park_only=True(주차 백필)면 세대수·용적률은 이미 있으므로 폴백 조건과
        표제부 응답 크기를 주차 기준으로만 잡는다(대단지에서 응답이 수십 배 작아짐).
        """
        addr = self.resolve(gu, umd, jibun)
        if not addr:
            return None

        recap = self._get_items(RECAP_EP, addr)
        result = {"households": None, "far": None, "bcr": None,
                  "approval_date": None, "park": {}}
        if recap:
            it = recap[0]
            result["households"] = _int(it.get("hhldCnt"))
            result["far"] = _ratio(it.get("vlRat"))
            result["bcr"] = _ratio(it.get("bcRat"))
            result["approval_date"] = _apr_date(it.get("useAprDay"))
            result["park"] = _park(it)

        # 총괄표제부에서 못 채운 값은 표제부(동별)로 폴백
        need_fallback = (not result["park"]) if park_only else not all(
            [result["households"], result["far"], result["bcr"], result["park"]])
        if need_fallback:
            titles = self._get_items(TITLE_EP, addr, rows=1 if park_only else 50)
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
                # ⚠주차는 표제부에서도 **필지 전체 값**이라 동마다 같은 수가 반복된다
                # (현대프라임 17개 동 전부 옥내 1,636 - 실측). 세대수처럼 합산하면
                # 17배로 부풀므로 최댓값을 쓴다.
                if not result["park"]:
                    ps = [p for p in (_park(t) for t in titles) if p]
                    if ps:
                        # indr/oudr 은 None(내역 미기재)일 수 있어 max() 에 섞으면
                        # TypeError - 값이 있는 것만 모으고, 하나도 없으면 None 유지
                        def _mx(k):
                            vals = [p[k] for p in ps if p.get(k) is not None]
                            return max(vals) if vals else None
                        result["park"] = {
                            "total": _mx("total"), "indr": _mx("indr"), "oudr": _mx("oudr"),
                        }

        if not any([result["households"], result["far"], result["bcr"],
                    result["approval_date"], result["park"]]):
            return None
        return result


def collect_buildings(conn, data_key: str, kakao_key: str,
                      lawd_cd: str | None = None, limit: int | None = None,
                      max_workers: int = 8, field: str = "bldg") -> dict:
    """건축물대장 정보 없는 단지를 조회해 저장. 통계 dict 반환.

    단지당 카카오 주소검색 1회 + 정부API 1~2회를 순차 호출해 건당 약 1.6초가
    걸린다(실측) - 수천 건 단위에서는 이게 병목이라 **네트워크 조회는 스레드풀로
    병렬화**하고(각 단지 조회는 완전히 독립적), DB 기록만 메인 스레드에서 순차
    처리한다(SQLite 쓰기는 스레드 안전이 아님 + 커밋 순서를 단순하게 유지).

    field='park' 는 주차 백필 모드 - 이미 수집된 단지를 재조회하므로 주차
    컬럼만 쓰고 기존 세대수·용적률은 건드리지 않는다(db.set_parking).
    """
    client = BuildingClient(data_key, kakao_key)
    targets = db.complexes_without_building(conn, lawd_cd, limit, field=field)
    stats = {"tried": 0, "filled": 0, "failed": 0}

    def _fetch(row):
        gu = config.SEOUL_DISTRICTS.get(row["lawd_cd"], "")
        try:
            return row, client.fetch(gu, row["umd_nm"], row["jibun"],
                                     park_only=(field == "park")), None
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
            if field == "park":
                # 백필: 주차만 기록(기존 세대수·용적률 보존). 빈손이어도 마커는 찍어 재조회 방지
                park = (info or {}).get("park") or {}
                db.set_parking(conn, row["complex_id"], park, now)
                if park:
                    stats["filled"] += 1
            elif info:
                db.set_building(conn, row["complex_id"], info["households"],
                                info["far"], info["bcr"], info["approval_date"],
                                now, info.get("park"))
                stats["filled"] += 1
            else:
                # 조회는 성공했으나 매칭되는 주소/데이터가 없음 - 재조회 방지 위해 시각만 기록
                db.set_building(conn, row["complex_id"], None, None, None, None, now)
            # 느린 API 대기 중 쓰기 락을 쥐지 않도록 매 건 즉시 커밋
            conn.commit()
            stats["tried"] += 1
    return stats
