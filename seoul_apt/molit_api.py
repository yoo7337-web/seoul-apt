"""국토교통부 아파트 실거래가 API 클라이언트(매매 + 전월세).

공공데이터포털 서비스(1613000):
  - 매매  : /RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade
  - 전월세: /RTMSDataSvcAptRent/getRTMSDataSvcAptRent
LAWD_CD(시군구 5자리) + DEAL_YMD(YYYYMM) 로 조회하며 XML 을 반환한다.
serviceKey 는 data.go.kr 의 Decoding 키를 넣으면 requests 가 알맞게 인코딩한다.
"""

import time
import xml.etree.ElementTree as ET

import requests

from . import config

BASE = "https://apis.data.go.kr/1613000"
TRADE_EP = f"{BASE}/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
RENT_EP = f"{BASE}/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"


class MolitAPIError(Exception):
    pass


def _to_int(text: str | None) -> int | None:
    if text is None:
        return None
    t = text.replace(",", "").strip()
    if t == "" or t == "-":
        return None
    try:
        return int(t)
    except ValueError:
        try:
            return int(float(t))
        except ValueError:
            return None


def _to_float(text: str | None) -> float | None:
    if text is None:
        return None
    t = text.replace(",", "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


class MolitClient:
    def __init__(self, service_key: str):
        self.service_key = service_key
        self.session = requests.Session()

    def _get_xml(self, endpoint: str, params: dict) -> ET.Element:
        params = dict(params)
        params["serviceKey"] = self.service_key
        last_err = None
        for attempt in range(config.MAX_RETRY):
            try:
                resp = self.session.get(endpoint, params=params,
                                        timeout=config.REQUEST_TIMEOUT)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                self._check_error(root)
                return root
            except (requests.RequestException, ET.ParseError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise MolitAPIError(f"요청 실패({endpoint}): {last_err}")

    @staticmethod
    def _check_error(root: ET.Element) -> None:
        # 정상: <response><header><resultCode>000</resultCode>...
        code = root.findtext(".//resultCode")
        if code is not None and code not in ("00", "000"):
            msg = root.findtext(".//resultMsg") or ""
            raise MolitAPIError(f"[{code}] {msg}")
        # 인증 오류: <OpenAPI_ServiceResponse>...<returnReasonCode>
        auth_msg = root.findtext(".//returnAuthMsg")
        if auth_msg:
            reason = root.findtext(".//returnReasonCode") or ""
            raise MolitAPIError(f"[{reason}] {auth_msg}")

    def _paged_items(self, endpoint: str, lawd_cd: str, deal_ymd: str):
        """페이지네이션하며 <item> 엘리먼트를 순회 yield."""
        page = 1
        total = None
        seen = 0
        while True:
            root = self._get_xml(endpoint, {
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ymd,
                "pageNo": page,
                "numOfRows": config.NUM_OF_ROWS,
            })
            if total is None:
                total = _to_int(root.findtext(".//totalCount")) or 0
            items = root.findall(".//item")
            if not items:
                break
            for item in items:
                yield item
                seen += 1
            if seen >= total or len(items) < config.NUM_OF_ROWS:
                break
            page += 1
            time.sleep(config.REQUEST_SLEEP)

    def fetch_sales(self, lawd_cd: str, deal_ymd: str) -> list[dict]:
        """아파트 매매 실거래 목록."""
        rows = []
        for it in self._paged_items(TRADE_EP, lawd_cd, deal_ymd):
            rows.append({
                "apt_nm": (it.findtext("aptNm") or "").strip(),
                "umd_nm": (it.findtext("umdNm") or "").strip() or None,
                "jibun": (it.findtext("jibun") or "").strip() or None,
                "build_year": _to_int(it.findtext("buildYear")),
                "exclu_area": _to_float(it.findtext("excluUseAr")),
                "floor": _to_int(it.findtext("floor")),
                "amount_manwon": _to_int(it.findtext("dealAmount")),
                "deal_date": self._deal_date(it),
            })
        return [r for r in rows if r["apt_nm"] and r["amount_manwon"]
                and r["exclu_area"] and r["deal_date"]]

    def fetch_rents(self, lawd_cd: str, deal_ymd: str) -> list[dict]:
        """아파트 전월세 실거래 목록."""
        rows = []
        for it in self._paged_items(RENT_EP, lawd_cd, deal_ymd):
            rows.append({
                "apt_nm": (it.findtext("aptNm") or "").strip(),
                "umd_nm": (it.findtext("umdNm") or "").strip() or None,
                "jibun": (it.findtext("jibun") or "").strip() or None,
                "build_year": _to_int(it.findtext("buildYear")),
                "exclu_area": _to_float(it.findtext("excluUseAr")),
                "floor": _to_int(it.findtext("floor")),
                "deposit_manwon": _to_int(it.findtext("deposit")) or 0,
                "monthly_manwon": _to_int(it.findtext("monthlyRent")) or 0,
                "deal_date": self._deal_date(it),
            })
        return [r for r in rows if r["apt_nm"] and r["exclu_area"]
                and r["deal_date"]]

    @staticmethod
    def _deal_date(item: ET.Element) -> str | None:
        y = _to_int(item.findtext("dealYear"))
        m = _to_int(item.findtext("dealMonth"))
        d = _to_int(item.findtext("dealDay"))
        if not (y and m and d):
            return None
        return f"{y:04d}-{m:02d}-{d:02d}"
