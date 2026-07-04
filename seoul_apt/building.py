"""건축물대장(건축HUB) 기반 단지 부가정보 - 세대수·용적률·건폐율·사용승인일.

국토부 건축HUB '건축물대장정보 서비스'(같은 DATA_GO_KR_KEY, 활용신청 필요).
좌표가 이미 있는(=지오코딩된) 단지에 대해:
  1) 카카오 주소검색으로 b_code(법정동 10자리) + 지번(본번/부번) + 산여부를 얻고
  2) 총괄표제부(getBrRecapTitleInfo)로 단지 전체 세대수·용적률·건폐율·사용승인일을 조회.
     비어 있으면 표제부(getBrTitleInfo)로 폴백(동별 세대수 합, 용적률/건폐율 최댓값).
값이 0/공란인 항목(구건물 등 미기재)은 None 으로 저장한다.
"""

import time
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


class BuildingClient:
    def __init__(self, data_key: str, kakao_key: str):
        self.data_key = data_key
        self.kakao_key = kakao_key
        self.session = requests.Session()

    # ── 주소 → 법정동코드/지번 ──────────────────────────────────────────
    def resolve(self, gu: str, umd: str | None, jibun: str | None) -> dict | None:
        """카카오 주소검색으로 (sigunguCd, bjdongCd, bun, ji, platGb) 반환."""
        parts = ["서울", gu]
        if umd:
            parts.append(umd)
        if jibun:
            parts.append(jibun)
        for attempt in range(config.MAX_RETRY):
            try:
                r = self.session.get(
                    KAKAO_ADDR, headers={"Authorization": f"KakaoAK {self.kakao_key}"},
                    params={"query": " ".join(parts)}, timeout=config.REQUEST_TIMEOUT)
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
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
            except (requests.RequestException, ValueError):
                time.sleep(2 ** attempt)
        return None

    def _get_items(self, endpoint: str, addr: dict) -> list[dict]:
        params = {
            "serviceKey": self.data_key,
            "sigunguCd": addr["sigunguCd"], "bjdongCd": addr["bjdongCd"],
            "platGbCd": addr["platGb"], "bun": addr["bun"], "ji": addr["ji"],
            "_type": "json", "numOfRows": "50",
        }
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
            except (requests.RequestException, ValueError):
                time.sleep(2 ** attempt)
        return []

    def fetch(self, gu: str, umd: str | None, jibun: str | None) -> dict | None:
        """단지 부가정보 dict 또는 None. 실패해도 예외 없이 None."""
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
                      lawd_cd: str | None = None, limit: int | None = None) -> dict:
    """건축물대장 정보 없는 단지를 조회해 저장. 통계 dict 반환."""
    client = BuildingClient(data_key, kakao_key)
    targets = db.complexes_without_building(conn, lawd_cd, limit)
    stats = {"tried": 0, "filled": 0}
    for i, row in enumerate(targets, 1):
        gu = config.SEOUL_DISTRICTS.get(row["lawd_cd"], "")
        info = client.fetch(gu, row["umd_nm"], row["jibun"])
        now = datetime.now(KST).isoformat(timespec="seconds")
        if info:
            db.set_building(conn, row["complex_id"], info["households"],
                            info["far"], info["bcr"], info["approval_date"], now)
            stats["filled"] += 1
        else:
            # 조회했으나 결과 없음 - 재조회 방지 위해 시각만 기록
            db.set_building(conn, row["complex_id"], None, None, None, None, now)
        # 느린 API 대기 중 쓰기 락을 쥐지 않도록 매 행 즉시 커밋(동시 수집 안전)
        conn.commit()
        stats["tried"] += 1
        time.sleep(config.REQUEST_SLEEP)
    return stats
