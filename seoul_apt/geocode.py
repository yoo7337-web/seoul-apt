"""카카오 로컬 API 지오코딩 - 단지 주소를 좌표로 변환하고 DB에 캐시.

좌표가 없는 신규 단지만 처리해 카카오 일일 쿼터 사용을 최소화한다.
카카오 주소검색: GET https://dapi.kakao.com/v2/local/search/address.json
  헤더 Authorization: KakaoAK {REST_KEY}, 응답 x=경도(lon), y=위도(lat)
"""

import time
from datetime import datetime, timezone, timedelta

import requests

from . import config, db

KAKAO_ADDR_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KST = timezone(timedelta(hours=9))


class KakaoGeocoder:
    def __init__(self, rest_key: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"KakaoAK {rest_key}"})

    def query_with_address(self, url: str, params: dict) -> tuple | None:
        """(lat, lon, 주소) 반환. 주소가 없는 공고(웹 캘린더 보조)의 구 판별용."""
        doc = self._query_doc(url, params)
        if not doc:
            return None
        addr = (doc.get("road_address_name") or doc.get("address_name")
                or (doc.get("address") or {}).get("address_name"))
        return float(doc["y"]), float(doc["x"]), addr

    def _query_doc(self, url: str, params: dict) -> dict | None:
        for attempt in range(config.MAX_RETRY):
            try:
                resp = self.session.get(url, params=params,
                                        timeout=config.REQUEST_TIMEOUT)
                if resp.status_code == 429:  # 쿼터 초과
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                docs = resp.json().get("documents") or []
                return docs[0] if docs else None
            except (requests.RequestException, KeyError, ValueError):
                time.sleep(2 ** attempt)
        return None

    def _query(self, url: str, params: dict) -> tuple[float, float] | None:
        d = self._query_doc(url, params)
        try:
            return (float(d["y"]), float(d["x"])) if d else None   # (lat, lon)
        except (KeyError, TypeError, ValueError):
            return None

    def geocode(self, gu: str, umd: str | None, jibun: str | None,
                apt_nm: str | None = None) -> tuple[float, float] | None:
        """지번주소 우선, 실패 시 '구+단지명' 키워드로 재시도."""
        parts = ["서울특별시", gu]
        if umd:
            parts.append(umd)
        if jibun:
            parts.append(jibun)
        addr = " ".join(parts)
        result = self._query(KAKAO_ADDR_URL, {"query": addr})
        if result:
            return result
        if apt_nm:
            kw = f"서울 {gu} {apt_nm}"
            return self._query(KAKAO_KEYWORD_URL, {"query": kw})
        return None


def geocode_missing(conn, rest_key: str, lawd_cd: str | None = None,
                    limit: int | None = None) -> int:
    """좌표 없는 단지를 지오코딩해 DB 업데이트. 처리한 건수 반환."""
    geocoder = KakaoGeocoder(rest_key)
    targets = db.complexes_without_coords(conn, lawd_cd)
    if limit:
        targets = targets[:limit]
    done = 0
    for row in targets:
        gu = config.SEOUL_DISTRICTS.get(row["lawd_cd"], "")
        coords = geocoder.geocode(gu, row["umd_nm"], row["jibun"], row["apt_nm"])
        if coords:
            now = datetime.now(KST).isoformat(timespec="seconds")
            db.set_coords(conn, row["complex_id"], coords[0], coords[1], now)
            done += 1
        time.sleep(config.REQUEST_SLEEP)
        if done % 50 == 0 and done:
            conn.commit()
    conn.commit()
    return done
