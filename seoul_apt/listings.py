"""현재 매물(호가) 수집 - 네이버부동산(주) + 직방(보조·폴백).

실거래(과거)와 달리 '지금 시장에 나온 매물'을 보여주기 위한 모듈.

네이버부동산은 TLS 핑거프린팅으로 일반 requests를 차단하므로 `curl_cffi`
(Chrome impersonation)로 우회한다. 확인된 무인증 경로(2026-07 검증):
  - 단지 매칭: new.land/api/search?keyword=단지명 → complexNo + 좌표 + cortarNo
  - 동 목록:   fin.land front-api /v1/complex/buildingList
  - 평형 목록: fin.land front-api /v1/complex/pyeongList
  - 매물:      fin.land front-api /v1/complex/building/article/list
               (complexNumber × buildingNumber × pyeongTypeNumber 순회)
new.land의 complexNo 와 fin.land의 complexNumber 는 같은 체계(검증됨).

차단 정책이 바뀌면 깨질 수 있으므로:
  - 저속(요청 간격) + 429 시 지수 백오프 + 세션 요청 상한
  - 진행상태(data/listings_state.json)로 중단 시 이어하기
  - 실패해도 직방 폴백 + 프런트 링크아웃(항상)으로 최소 기능 보장
GitHub Actions(해외 IP)는 차단 위험이 커 네이버 수집은 로컬 실행 전제.
"""

import json
import random
import time
from datetime import datetime, timezone, timedelta

from . import config, db
from .aggregate import _dist_km, _median

KST = timezone(timedelta(hours=9))

NEW_LAND = "https://new.land.naver.com/api"
FIN_API = "https://fin.land.naver.com/front-api/v1"
ZIGBANG = "https://apis.zigbang.com"

# 매칭 허용 오차(단지 좌표 최근접)
MATCH_MAX_M = 120
# 호가 괴리 계산: 전용면적 ±12% + 최근 1년 실거래 대비
PREM_AREA_TOL = 0.12
PREM_MONTHS = 12
PREM_MIN_SAMPLE = 3

STATE_PATH = config.DATA_DIR / "listings_state.json"

# 네이버 tradeType 코드 → 우리 표준
NAVER_TRADE = {"A1": "sale", "B1": "jeonse", "B2": "wolse"}
# 향 코드 정규화(네이버 2글자 방위)
_DIR = {"E": "동", "W": "서", "S": "남", "N": "북",
        "SE": "남동", "SW": "남서", "NE": "북동", "NW": "북서",
        "EE": "동", "WW": "서", "SS": "남", "NN": "북",
        "ES": "남동", "WS": "남서", "EN": "북동", "WN": "북서"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dir_ko(code: str | None) -> str | None:
    if not code:
        return None
    return _DIR.get(code.upper(), code)


# ── curl_cffi 세션 ──────────────────────────────────────────────────────
class NaverBlockedError(Exception):
    """네이버가 반복 429/차단으로 세션을 중단해야 함(다음 실행에서 이어하기)."""


class NaverLandClient:
    """네이버부동산(new.land 검색 + fin.land 매물) 클라이언트.

    curl_cffi 없이 생성하면 즉시 실패한다(호출부에서 직방 폴백 판단).
    """

    def __init__(self, sleep: float = 1.2, jitter: float = 0.6,
                 max_requests: int = 4000):
        from curl_cffi import requests as cr  # 지연 import(미설치 환경 보호)
        self._cr = cr
        self.s = cr.Session(impersonate="chrome")
        self.sleep = sleep
        self.jitter = jitter
        self.max_requests = max_requests
        self._count = 0
        self._backoff = 60
        # new.land 는 첫 방문으로 쿠키 세팅
        try:
            self.s.get("https://new.land.naver.com/", timeout=config.REQUEST_TIMEOUT)
        except Exception:
            pass

    def _pace(self):
        time.sleep(self.sleep + random.random() * self.jitter)

    def _req(self, method, url, *, referer, **kw):
        """호출 + 429 백오프 + 요청 상한. 반환은 파싱된 dict(result) 또는 None."""
        if self._count >= self.max_requests:
            raise NaverBlockedError(
                f"세션 요청 상한({self.max_requests}) 도달 - 안전 중단")
        headers = kw.pop("headers", {})
        headers["Referer"] = referer
        for attempt in range(3):
            self._count += 1
            r = self.s.request(method, url, headers=headers,
                               timeout=config.REQUEST_TIMEOUT, **kw)
            if r.status_code == 429:
                if self._backoff > 240:
                    raise NaverBlockedError("반복 429 - 세션 중단(다음 실행 재개)")
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 300)
                continue
            self._pace()
            if r.status_code != 200:
                return None
            try:
                return r.json()
            except Exception:
                return None
        return None

    # -- 단지 매칭 --
    def search_complex(self, name: str) -> list[dict]:
        """단지명 검색 → [{no, name, lat, lon, cortarNo, households}]."""
        import urllib.parse
        ref = "https://new.land.naver.com/search?sk=" + urllib.parse.quote(name)
        d = self._req("GET", NEW_LAND + "/search",
                      params={"keyword": name, "page": 1}, referer=ref)
        out = []
        for c in (d or {}).get("complexes", []) or []:
            try:
                out.append({
                    "no": str(c["complexNo"]),
                    "name": c.get("complexName", ""),
                    "lat": float(c["latitude"]), "lon": float(c["longitude"]),
                    "cortarNo": c.get("cortarNo"),
                    "households": c.get("totalHouseholdCount"),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return out

    # -- 매물 --
    def _fin(self, path, params):
        ref = f"https://fin.land.naver.com/complexes/{params.get('complexNumber','')}"
        d = self._req("GET", FIN_API + path, params=params, referer=ref)
        return (d or {}).get("result")

    def buildings(self, no: str) -> list[dict]:
        return self._fin("/complex/buildingList", {"complexNumber": no}) or []

    def pyeong_types(self, no: str) -> list[dict]:
        return self._fin("/complex/pyeongList", {"complexNumber": no}) or []

    def article_count(self, no: str) -> dict | None:
        return self._fin("/complex/article/count", {"complexNumber": no})

    def complex_articles(self, no: str) -> list[dict]:
        """단지의 모든 매물(대표매물 기준). 동 × 평형 순회.

        같은 물건을 여러 중개사가 올린 중복은 대표매물 1건으로 취급.
        건물별 매물수(building/article/count)로 0인 동은 건너뛰어 요청 절약.
        """
        bcount = self._fin("/complex/building/article/count", {"complexNumber": no}) or []
        active_bnos = [b["buildingNumber"] for b in bcount if b.get("articleCount")]
        expected = sum(b.get("articleCount") or 0 for b in bcount)
        if not active_bnos:                    # count 비면 전체 동 시도
            active_bnos = [b["number"] for b in self.buildings(no)]
        pts = [p["number"] for p in self.pyeong_types(no)]
        seen = set()
        out = []
        for bno in active_bnos:
            for pt in pts:
                res = self._fin("/complex/building/article/list",
                                {"complexNumber": no, "buildingNumber": bno,
                                 "pyeongTypeNumber": pt})
                arts = (res or {}).get("articles") or {}
                for grp in arts.values():
                    for item in grp:
                        rec = _parse_naver_article(item, no)
                        if rec and rec["item_id"] not in seen:
                            seen.add(rec["item_id"])
                            out.append(rec)
        if expected and not out:
            # 집계 API(건별 카운트)는 매물이 있다는데 상세 목록은 항상 비어 온다 -
            # 약 40개 표본 중 3곳(~7.5%)에서 재현된 네이버 쪽 현상(광진구 현대프라임
            # 등). 매칭 오류나 우리 쪽 차단이 아니라 이 단지에 한정된 응답이므로,
            # '진짜 매물 없음'과 구분되게 로그로 남긴다(조용히 0건 기록 금지).
            print(f"[listings] complexNumber={no} 집계상 매물 {expected}건이나 "
                  f"상세 0건 반환 - 네이버 노출제한 추정(직방 폴백으로 보완)")
        return out


def _parse_naver_article(item: dict, complex_no: str) -> dict | None:
    """fin.land 대표매물 항목 → 표준 매물 dict."""
    rep = item.get("representativeArticleInfo") or {}
    art_no = rep.get("articleNumber")
    if not art_no:
        return None
    price = rep.get("priceInfo") or {}
    space = rep.get("spaceInfo") or {}
    detail = rep.get("articleDetail") or {}
    floor_d = detail.get("floorDetailInfo") or {}
    trade = NAVER_TRADE.get(rep.get("tradeType"), "sale")
    deal = price.get("dealPrice") or 0
    warranty = price.get("warrantyPrice") or 0
    rent = price.get("rentPrice") or 0
    # 매매=dealPrice, 전세/월세=warrantyPrice(보증금)
    if trade == "sale":
        price_manwon = round(deal / 10000) if deal else None
        monthly = 0
    else:
        price_manwon = round(warranty / 10000) if warranty else None
        monthly = round(rent / 10000) if rent else 0
    return {
        "source": "naver",
        "item_id": str(art_no),
        "trade_type": trade,
        "price_manwon": price_manwon,
        "monthly_manwon": monthly,
        "area_m2": space.get("exclusiveSpace"),
        "floor": _to_int(floor_d.get("targetFloor")),
        "floor_total": _to_int(floor_d.get("totalFloor")),
        "dong": rep.get("dongName"),
        "direction": _dir_ko(detail.get("direction")),
        "description": None,   # 대표매물엔 코멘트 없음(상세 API 별도 - 생략)
        "confirm_date": (rep.get("verificationInfo") or {}).get("articleConfirmDate"),
        "url": f"https://fin.land.naver.com/complexes/{complex_no}?articleNo={art_no}",
    }


def _to_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ── 직방(폴백·보조) ─────────────────────────────────────────────────────
class ZigbangClient:
    """직방 공개 API(무인증). 네이버 실패 시 폴백/보완."""

    def __init__(self):
        import requests
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"

    def search_danji(self, name: str) -> list[dict]:
        r = self.s.get(ZIGBANG + "/v2/search",
                       params={"leaseYn": "N", "q": name, "serviceType": "아파트"},
                       timeout=config.REQUEST_TIMEOUT)
        out = []
        for it in (r.json().get("items", []) if r.ok else []):
            if it.get("type") != "apartment":
                continue
            src = it.get("_source", {})
            out.append({"id": it["id"], "name": it.get("name", ""),
                        "lat": it.get("lat"), "lon": it.get("lng"),
                        "bcode": src.get("법정동코드")})
        return out

    def danji_items(self, danji_id: int, trade: str) -> list[dict]:
        # trade: 'sale'→trade, 'jeonse'→charter
        tt = "trade" if trade == "sale" else "charter"
        r = self.s.get(ZIGBANG + f"/apt/danjis/{danji_id}/items",
                       params={"tradeType": tt}, timeout=config.REQUEST_TIMEOUT)
        out = []
        for a in (r.json().get("list", []) if r.ok else []):
            rt = (a.get("roomTypeData") or {}).get("전용면적", {})
            out.append({
                "source": "zigbang", "item_id": f"zb{a['itemId']}",
                "trade_type": "sale" if a.get("tranType") == "trade" else "jeonse",
                "price_manwon": a.get("deposit"), "monthly_manwon": a.get("rent") or 0,
                "area_m2": rt.get("m2"),
                "floor": _to_int(a.get("floor")), "floor_total": _to_int(a.get("buildingFloor")),
                "dong": a.get("areaBuildingName"), "direction": _dir_ko(a.get("direction")),
                "description": a.get("description"),
                "confirm_date": (a.get("updatedAt") or "")[:10] or None,
                "url": f"https://www.zigbang.com/home/apt/danjis/{danji_id}",
            })
        return out


# ── 단지 매칭 ────────────────────────────────────────────────────────────
def _name_affinity(a: str, b: str) -> bool:
    """두 단지명이 '같은 단지'로 볼 만한가(정규화 후 부분집합 또는 토큰 겹침)."""
    na, nb = db.normalize_apt_name(a), db.normalize_apt_name(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    # 3글자 이상 접두 공통(예: '인왕산아이파크' vs '인왕산현대아이파크'는
    # 접두 '인왕산' 공통) — 좌표가 가까울 때 보조 신호로만 사용
    return na[:3] == nb[:3]


def match_naver_no(conn, complex_id, name, lat, lon, client) -> str | None:
    """네이버 검색 결과에서 좌표 최근접(±MATCH_MAX_M)으로 complexNo 확정.

    좌표를 주 신호로 쓴다(호갱노노식 단지 좌표는 정확). 이름은 표기 차이
    ('인왕산아이파크' vs '인왕산현대아이파크', 괄호·차수)가 잦아 보조로만.
    괄호가 든 검색어는 0건이 나오므로 괄호를 떼고도 검색한다.
    """
    import re
    queries = [name]
    stripped = re.sub(r"\(.*?\)", "", name).strip()
    if stripped and stripped != name:
        queries.append(stripped)
    cands = []
    for q in queries:
        try:
            cands = client.search_complex(q)
        except Exception:
            cands = []
        if cands:
            break
    # 1순위: 이름 유사 + 좌표 근접(±120m). 2순위: 이름 안 맞아도 좌표 초근접
    # (±50m)이면 표기차(쥬↔주, 국토부↔네이버 명칭)로 보고 채택.
    best, best_m = None, MATCH_MAX_M
    coord_best, coord_m = None, 50.0
    for c in cands:
        d = _dist_km(lat, lon, c["lat"], c["lon"]) * 1000
        if d <= best_m and _name_affinity(name, c["name"]):
            best, best_m = c, d
        if d <= coord_m:
            coord_best, coord_m = c, d
    chosen = best or coord_best
    return chosen["no"] if chosen else None


# ── 상태 저장(중단 재개) ──────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done_complex_ids": []}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ── 저장(스냅샷 diff → gone 처리) ────────────────────────────────────────
def upsert_listings(conn, complex_id: int, records: list[dict], now: str) -> dict:
    """이번 수집 스냅샷을 반영. 이전에 open 이었는데 이번에 없는 매물은 gone."""
    seen_ids = set()
    for r in records:
        seen_ids.add((r["source"], r["item_id"]))
        row = conn.execute(
            "SELECT id FROM listing WHERE source=? AND item_id=?",
            (r["source"], r["item_id"])).fetchone()
        if row:
            conn.execute(
                "UPDATE listing SET price_manwon=?, monthly_manwon=?, area_m2=?, "
                "floor=?, floor_total=?, dong=?, direction=?, description=?, "
                "confirm_date=?, url=?, last_seen=?, status='open', complex_id=? "
                "WHERE id=?",
                (r["price_manwon"], r["monthly_manwon"], r["area_m2"], r["floor"],
                 r["floor_total"], r["dong"], r["direction"], r["description"],
                 r["confirm_date"], r["url"], now, complex_id, row["id"]))
        else:
            conn.execute(
                "INSERT INTO listing(source, item_id, complex_id, trade_type, "
                "price_manwon, monthly_manwon, area_m2, floor, floor_total, dong, "
                "direction, description, confirm_date, url, first_seen, last_seen, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open')",
                (r["source"], r["item_id"], complex_id, r["trade_type"],
                 r["price_manwon"], r["monthly_manwon"], r["area_m2"], r["floor"],
                 r["floor_total"], r["dong"], r["direction"], r["description"],
                 r["confirm_date"], r["url"], now, now))
    # 이번 스냅샷에 없는 기존 open 매물 → gone
    gone = 0
    existing = conn.execute(
        "SELECT id, source, item_id FROM listing "
        "WHERE complex_id=? AND status='open'", (complex_id,)).fetchall()
    for e in existing:
        if (e["source"], e["item_id"]) not in seen_ids:
            conn.execute("UPDATE listing SET status='gone', last_seen=? WHERE id=?",
                         (now, e["id"]))
            gone += 1
    conn.commit()
    return {"added_or_updated": len(records), "gone": gone}


# ── 호가 괴리(±12% 최근 1년 실거래 대비) ─────────────────────────────────
def asking_premium(conn, complex_id, area_m2, price_manwon, trade_type) -> float | None:
    """매물 호가가 같은 크기 최근 실거래 중앙값 대비 몇 % 인지(+비쌈/-쌈).

    가격 비교 대원칙(같은 크기 ±12% + 최근 1년) 재사용. 매매만(전세 실거래
    테이블은 rent_txn 이라 여기선 매매 호가에 대해서만 계산). 표본<3이면 None.
    """
    if trade_type != "sale" or not area_m2 or not price_manwon:
        return None
    lo, hi = area_m2 * (1 - PREM_AREA_TOL), area_m2 * (1 + PREM_AREA_TOL)
    since = (datetime.now(KST).date() - timedelta(days=PREM_MONTHS * 30)).isoformat()
    amounts = [r["amount_manwon"] for r in conn.execute(
        "SELECT amount_manwon FROM sale_txn WHERE complex_id=? AND canceled=0 "
        "AND deal_date>=? AND exclu_area BETWEEN ? AND ?",
        (complex_id, since, lo, hi)).fetchall()]
    if len(amounts) < PREM_MIN_SAMPLE:
        return None
    med = _median(amounts)
    if not med:
        return None
    return round((price_manwon - med) / med * 100, 1)


# ── 수집 오케스트레이션 ──────────────────────────────────────────────────
ACTIVE_FILTER = (
    " AND complex_id IN ("
    "  SELECT complex_id FROM sale_txn WHERE canceled=0 "
    "  AND deal_date>=date('now','-365 days') "
    "  GROUP BY complex_id HAVING COUNT(*)>=3)")


def _target_complexes(conn, scope: str, district: str | None = None,
                      active_only: bool = True) -> list:
    """수집 대상 단지 rows(complex_id, apt_nm, lat, lon, naver_no).

    district(lawd_cd)를 주면 그 구로 한정. active_only=True 면 최근 1년 매매
    3건 이상인 단지만(거래 없는 단지는 매물도 거의 없어 요청 낭비).
    """
    sql = ("SELECT complex_id, apt_nm, lat, lon, naver_no FROM complex "
           "WHERE lat IS NOT NULL AND lon IS NOT NULL")
    params = []
    if district:
        sql += " AND lawd_cd=?"
        params.append(district)
    if scope == "seoul" and not district:
        return conn.execute(sql, params).fetchall()
    # favorites 는 프런트 localStorage라 서버가 모름 → 거래 활발 단지로 근사
    if active_only:
        sql += ACTIVE_FILTER
    return conn.execute(sql, params).fetchall()


def collect(conn, scope="watch", source="auto", limit=None, resume=True,
            district=None, active_only=True) -> dict:
    """매물 수집. source: auto(네이버 우선)|naver|zigbang."""
    now = _now()
    naver = None
    if source in ("auto", "naver"):
        try:
            naver = NaverLandClient()
        except Exception as e:
            if source == "naver":
                raise RuntimeError(f"curl_cffi 미설치 등으로 네이버 클라이언트 생성 실패: {e}")
    zig = ZigbangClient() if source in ("auto", "zigbang") else None

    targets = _target_complexes(conn, scope, district, active_only)
    state = load_state() if resume else {"done_complex_ids": []}
    done = set(state.get("done_complex_ids", []))
    stats = {"complexes": 0, "listings": 0, "naver": 0, "zigbang": 0,
             "blocked": False, "skipped_matched": 0}
    processed = 0
    for row in targets:
        cid = row["complex_id"]
        if cid in done:
            continue
        if limit and processed >= limit:
            break
        records = []
        used = None
        # 1) 네이버
        if naver is not None:
            no = row["naver_no"]
            if not no:
                no = match_naver_no(conn, cid, row["apt_nm"], row["lat"], row["lon"], naver)
                if no:
                    conn.execute("UPDATE complex SET naver_no=?, listing_matched_at=? "
                                 "WHERE complex_id=?", (no, now, cid))
                    conn.commit()
            if no:
                try:
                    records = naver.complex_articles(no)
                    used = "naver"
                except NaverBlockedError:
                    stats["blocked"] = True
                    save_state({"done_complex_ids": list(done)})
                    break
                except Exception:
                    records = []
        # 2) 직방 폴백(네이버 0건이거나 source=zigbang)
        if (not records) and zig is not None:
            try:
                danjis = zig.search_danji(row["apt_nm"])
                best = _match_zigbang(row, danjis)
                if best:
                    if not conn.execute("SELECT zigbang_id FROM complex WHERE complex_id=?",
                                        (cid,)).fetchone()["zigbang_id"]:
                        conn.execute("UPDATE complex SET zigbang_id=? WHERE complex_id=?",
                                     (best["id"], cid))
                    for tt in ("sale", "jeonse"):
                        records += zig.danji_items(best["id"], tt)
                    used = "zigbang"
            except Exception:
                pass
        if records:
            upsert_listings(conn, cid, records, now)
            stats["listings"] += len(records)
            stats[used] = stats.get(used, 0) + len(records)
            stats["complexes"] += 1
        done.add(cid)
        processed += 1
    save_state({"done_complex_ids": list(done)})
    return stats


def _match_zigbang(row, danjis) -> dict | None:
    best, best_m = None, MATCH_MAX_M
    norm = db.normalize_apt_name(row["apt_nm"])
    for d in danjis:
        if d["lat"] is None or d["lon"] is None:
            continue
        m = _dist_km(row["lat"], row["lon"], d["lat"], d["lon"]) * 1000
        name_ok = norm in db.normalize_apt_name(d["name"]) or \
            db.normalize_apt_name(d["name"]) in norm
        if m <= best_m and name_ok:
            best, best_m = d, m
    return best
