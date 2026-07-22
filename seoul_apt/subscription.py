"""청약홈 분양정보·경쟁률 수집 (한국부동산원, data.go.kr odcloud API).

서비스 2종(둘 다 DATA_GO_KR_KEY 로 활용신청 필요):
  - 분양정보: ApplyhomeInfoDetailSvc  (APT 공고/주택형, 무순위·잔여세대)
  - 경쟁률  : ApplyhomeInfoCmpetRtSvc (주택형별 접수건수·경쟁률)
호출 형식: GET https://api.odcloud.kr/api/<svc>/v1/<op>
             ?page=&perPage=&cond[필드::EQ]=값&serviceKey=
응답: {"data":[{...대문자_스네이크 필드...}], "totalCount": n, ...}

수집 범위: 서울(SUBSCRPT_AREA_CODE_NM='서울'), 기본 최근 18개월 공고.
필드명이 API 버전에 따라 다를 수 있어 _field() 로 후보명을 순차 조회한다.
"""

import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import config, db
from .geocode import KakaoGeocoder, KAKAO_ADDR_URL, KAKAO_KEYWORD_URL

KST = timezone(timedelta(hours=9))
BASE = "https://api.odcloud.kr/api"
DETAIL_SVC = f"{BASE}/ApplyhomeInfoDetailSvc/v1"
CMPET_SVC = f"{BASE}/ApplyhomeInfoCmpetRtSvc/v1"

OP_APT = f"{DETAIL_SVC}/getAPTLttotPblancDetail"          # APT 분양공고(특별/1·2순위)
OP_APT_MDL = f"{DETAIL_SVC}/getAPTLttotPblancMdl"          # APT 주택형별
OP_REMNDR = f"{DETAIL_SVC}/getRemndrLttotPblancDetail"     # 무순위/잔여세대 + 불법행위 재공급
OP_REMNDR_MDL = f"{DETAIL_SVC}/getRemndrLttotPblancMdl"
OP_OPTN = f"{DETAIL_SVC}/getOPTLttotPblancDetail"          # 임의공급
OP_APT_CMPET = f"{CMPET_SVC}/getAPTLttotPblancCmpet"       # APT 경쟁률

# API 오퍼레이션 → (엔드포인트, 주택형 엔드포인트|None)
_KIND_EP = {
    "apt": (OP_APT, OP_APT_MDL),
    "remndr": (OP_REMNDR, OP_REMNDR_MDL),
    "optn": (OP_OPTN, None),        # 임의공급은 주택형 오퍼레이션 미제공
}

DEFAULT_SINCE_MONTHS = 18   # 모집공고일 기준 수집 범위
PER_PAGE = 100


class SubscriptionAPIError(Exception):
    pass


def _to_int(v) -> int | None:
    if v is None:
        return None
    t = str(v).replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    t = str(v).replace(",", "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _field(raw: dict, *names, default=None):
    """API 필드명 변형(대소문자·표기 차이)을 흡수해 첫 매칭값 반환."""
    lower = {k.lower(): v for k, v in raw.items()}
    for n in names:
        if n in raw:
            return raw[n]
        if n.lower() in lower:
            return lower[n.lower()]
    return default


class ApplyhomeClient:
    def __init__(self, service_key: str, debug: bool = False):
        self.key = service_key
        self.debug = debug
        self.session = requests.Session()
        self._dumped: set[str] = set()

    def _get_rows(self, endpoint: str, cond: dict | None = None) -> list[dict]:
        """페이지 순회하며 data 행 전부 수집."""
        rows: list[dict] = []
        page = 1
        while True:
            params = {"page": page, "perPage": PER_PAGE,
                      "serviceKey": self.key, "returnType": "JSON"}
            for k, v in (cond or {}).items():
                params[f"cond[{k}]"] = v
            last_err = None
            for attempt in range(config.MAX_RETRY):
                try:
                    resp = self.session.get(endpoint, params=params,
                                            timeout=config.REQUEST_TIMEOUT)
                    if resp.status_code in (401, 403):
                        raise SubscriptionAPIError(
                            f"인증 실패({resp.status_code}) - data.go.kr 에서 "
                            f"청약홈 API 활용신청이 승인됐는지 확인하세요: {endpoint}")
                    resp.raise_for_status()
                    j = resp.json()
                    break
                except SubscriptionAPIError:
                    raise
                except (requests.RequestException, ValueError) as e:
                    last_err = e
                    time.sleep(2 ** attempt)
            else:
                raise SubscriptionAPIError(f"요청 실패({endpoint}): {last_err}")

            data = j.get("data") or []
            if self.debug and data and endpoint not in self._dumped:
                self._dumped.add(endpoint)
                print(f"[subscription:debug] {endpoint.rsplit('/', 1)[-1]} "
                      f"필드: {sorted(data[0].keys())}")
            rows.extend(data)
            total = j.get("totalCount") or 0
            if len(rows) >= total or not data:
                break
            page += 1
            time.sleep(config.REQUEST_SLEEP)
        return rows

    def fetch_notices(self, kind: str, since: str) -> list[dict]:
        """분양공고 목록(서울, 모집공고일>=since). kind: 'apt'|'remndr'|'optn'."""
        ep = _KIND_EP[kind][0]
        raws = self._get_rows(ep, {
            "SUBSCRPT_AREA_CODE_NM::EQ": "서울",
            "RCRIT_PBLANC_DE::GTE": since,
        })
        return [_parse_notice(r, kind) for r in raws]

    def fetch_models(self, kind: str, house_manage_no: str) -> list[dict]:
        ep = _KIND_EP[kind][1]
        if not ep:                      # 임의공급 등 주택형 오퍼레이션 없는 유형
            return []
        raws = self._get_rows(ep, {"HOUSE_MANAGE_NO::EQ": house_manage_no})
        return [_parse_model(r, house_manage_no) for r in raws]

    def fetch_cmpet(self, house_manage_no: str) -> list[dict]:
        """APT 경쟁률(무순위는 전용 오퍼레이션이 없어 APT 만)."""
        raws = self._get_rows(OP_APT_CMPET,
                              {"HOUSE_MANAGE_NO::EQ": house_manage_no})
        return [_parse_cmpet(r, house_manage_no) for r in raws]


# ── 파싱(테스트 가능하도록 분리) ─────────────────────────────────────────
def _parse_notice(raw: dict, kind: str) -> dict:
    # 공급유형(HOUSE_SECD_NM): 무순위/불법행위 재공급/임의공급 등. remndr 오퍼레이션이
    # 무순위와 불법행위 재공급을 함께 반환하므로 이 라벨로 구분한다. APT 정규공고는
    # HOUSE_SECD_NM 이 '분양주택' 등이라, kind=apt 는 별도 라벨로 덮어씀.
    secd = (_field(raw, "HOUSE_SECD_NM") or "").strip() or None
    if kind == "apt":
        secd = "일반공급"
    return {
        "house_manage_no": str(_field(raw, "HOUSE_MANAGE_NO") or ""),
        "pblanc_no": str(_field(raw, "PBLANC_NO") or "") or None,
        "kind": kind,
        "secd_nm": secd,
        "house_nm": (_field(raw, "HOUSE_NM") or "").strip(),
        "adres": (_field(raw, "HSSPLY_ADRES") or "").strip() or None,
        "tot_suply": _to_int(_field(raw, "TOT_SUPLY_HSHLDCO")),
        "rcrit_de": _field(raw, "RCRIT_PBLANC_DE"),
        "rcept_bgnde": _field(raw, "RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE"),
        "rcept_endde": _field(raw, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE"),
        "przwner_de": _field(raw, "PRZWNER_PRESNATN_DE"),
        "cntrct_bgnde": _field(raw, "CNTRCT_CNCLS_BGNDE"),
        "cntrct_endde": _field(raw, "CNTRCT_CNCLS_ENDDE"),
        "mvn_ym": _field(raw, "MVN_PREARNGE_YM"),
        "cnstrct_nm": (_field(raw, "CNSTRCT_ENTRPS_NM") or "").strip() or None,
        "url": _field(raw, "PBLANC_URL"),
    }


def _parse_model(raw: dict, house_manage_no: str) -> dict:
    ty = (_field(raw, "HOUSE_TY", "TP") or "").strip()
    model_no = str(_field(raw, "MODEL_NO") or "").strip()
    return {
        "house_manage_no": house_manage_no,
        "house_ty": ty or model_no or "-",
        "suply_ar": _to_float(_field(raw, "SUPLY_AR", "EXCLUSE_AR")),
        "suply_hshldco": _to_int(_field(raw, "SUPLY_HSHLDCO")),
        "spsply_hshldco": _to_int(_field(raw, "SPSPLY_HSHLDCO")),
        # 분양최고금액 - API 단위가 만원
        "top_amount": _to_int(_field(raw, "LTTOT_TOP_AMOUNT", "TOP_AMOUNT")),
    }


def _parse_cmpet(raw: dict, house_manage_no: str) -> dict:
    # 같은 주택형·지역에 1·2순위 행이 따로 오므로 순위를 구분 라벨에 포함
    resd = (_field(raw, "RESIDE_SENM", "RESIDE_SECD_NM",
                   "RESIDE_SECD") or "").strip()
    rank = _to_int(_field(raw, "SUBSCRPT_RANK_CODE"))
    if rank:
        resd = f"{resd} {rank}순위".strip()
    return {
        "house_manage_no": house_manage_no,
        "house_ty": (_field(raw, "HOUSE_TY", "TP") or "-").strip(),
        "reside_secd": resd,
        "req_cnt": _to_int(_field(raw, "REQ_CNT", "RCEPT_CNT")),
        "cmpet_rate": (str(_field(raw, "CMPET_RATE") or "").strip() or None),
    }


def extract_gu(adres: str | None) -> str | None:
    """공급위치 주소에서 '○○구' 추출."""
    if not adres:
        return None
    m = re.search(r"서울[^ ]*\s+(\S+?구)", adres)
    return m.group(1) if m else None


# ── 수집 파이프라인 ──────────────────────────────────────────────────────
def collect_subscriptions(conn, data_key: str, kakao_key: str | None = None,
                          since: str | None = None,
                          debug: bool = False) -> dict:
    """공고+주택형+경쟁률 수집 → upsert → 지오코딩. 통계 dict 반환."""
    if since is None:
        since = (date.today() - timedelta(days=DEFAULT_SINCE_MONTHS * 30)) \
            .isoformat()
    client = ApplyhomeClient(data_key, debug=debug)
    now = datetime.now(KST).isoformat(timespec="seconds")
    today = date.today().isoformat()
    stats = {"apt": 0, "remndr": 0, "optn": 0, "models": 0, "cmpet": 0, "geocoded": 0}

    for kind in ("apt", "remndr", "optn"):
        try:
            notices = client.fetch_notices(kind, since)
        except SubscriptionAPIError as e:
            print(f"[subscription] {kind} 수집 건너뜀: {e}")
            continue
        for n in notices:
            if not n["house_manage_no"] or not n["house_nm"]:
                continue
            n["fetched_at"] = now
            db.upsert_subscription(conn, n)
            stats[kind] += 1
            # 주택형별 분양가
            try:
                for m in client.fetch_models(kind, n["house_manage_no"]):
                    db.upsert_subscription_model(conn, m)
                    stats["models"] += 1
            except SubscriptionAPIError as e:
                print(f"[subscription] 주택형 조회 실패({n['house_nm']}): {e}")
            # 경쟁률 - 접수 마감된 APT 공고만 존재
            if kind == "apt" and n["rcept_endde"] and n["rcept_endde"] <= today:
                try:
                    for c in client.fetch_cmpet(n["house_manage_no"]):
                        db.upsert_subscription_cmpet(conn, c)
                        stats["cmpet"] += 1
                except SubscriptionAPIError as e:
                    print(f"[subscription] 경쟁률 조회 실패({n['house_nm']}): {e}")
            time.sleep(config.REQUEST_SLEEP)
        conn.commit()

    if kakao_key:
        stats["geocoded"] = _geocode_missing(conn, kakao_key)
    conn.commit()
    return stats


def _geocode_missing(conn, kakao_key: str) -> int:
    """공급위치 주소로 좌표 채우기(주소검색 → 실패 시 주택명 키워드)."""
    geocoder = KakaoGeocoder(kakao_key)
    done = 0
    for row in db.subscriptions_without_coords(conn):
        coords = geocoder._query(KAKAO_ADDR_URL, {"query": row["adres"]})
        if not coords:
            coords = geocoder._query(
                KAKAO_KEYWORD_URL, {"query": f"서울 {row['house_nm']}"})
        if coords:
            db.set_subscription_coords(conn, row["house_manage_no"],
                                       coords[0], coords[1])
            done += 1
        time.sleep(config.REQUEST_SLEEP)
    return done
