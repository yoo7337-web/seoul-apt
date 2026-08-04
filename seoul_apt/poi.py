"""입지 레이어(역세권·초품아) — 정적 POI 적재 + 단지별 최근접 거리 계산.

지하철역·초등학교는 준불변 데이터라 1회 적재하면 된다. 좌표를 가진 단지에
대해 haversine 최근접 POI를 찾아 `complex.subway_m / subway_nm / school_m`를
채운다(미계산 단지만 증분 처리). daily Action 불필요.

데이터 소스(1회성, `data/poi/`에 CSV로 커밋):
- `subway_stations.csv` : 전국도시철도역사정보표준데이터(KRIC) 수도권 필터
  컬럼 name,line,lat,lon
- `schools_seoul.csv`    : NEIS 서울 초등학교 + 카카오 지오코딩
  컬럼 name,lat,lon
"""

import csv
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config
from .aggregate import _dist_km

POI_DIR = config.DATA_DIR / "poi"
SUBWAY_CSV = POI_DIR / "subway_stations.csv"
SCHOOL_CSV = POI_DIR / "schools_seoul.csv"

# 최근접 탐색 상한(m) — 이보다 멀면 "역세권/초품아 아님"으로 NULL 처리해
# 지도·필터에서 무한대 취급. 서울 도심 밀도상 지하철 2km·초등 1.5km면 충분.
SUBWAY_MAX_M = 2000
SCHOOL_MAX_M = 1500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_poi(conn: sqlite3.Connection) -> dict:
    """data/poi/*.csv 를 poi 테이블에 멱등 적재. 적재 건수 반환."""
    stats = {"subway": 0, "elem": 0}
    if SUBWAY_CSV.exists():
        stats["subway"] = _load_csv(
            conn, SUBWAY_CSV, "subway",
            lambda r: (r["name"], r.get("line", ""), r["lat"], r["lon"]),
        )
    if SCHOOL_CSV.exists():
        stats["elem"] = _load_csv(
            conn, SCHOOL_CSV, "elem",
            lambda r: (r["name"], None, r["lat"], r["lon"]),
        )
    conn.commit()
    return stats


def _load_csv(conn, path: Path, kind: str, extract) -> int:
    n = 0
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name, line, lat, lon = extract(row)
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO poi(kind, name, line, lat, lon) "
                "VALUES (?,?,?,?,?)",
                (kind, name, line, lat, lon),
            )
            n += cur.rowcount
    return n


def _nearest(lat, lon, pois, max_m):
    """(거리m, poi_row) 최근접 반환. 없거나 상한 초과면 (None, None)."""
    best_km, best = None, None
    for p in pois:
        d = _dist_km(lat, lon, p["lat"], p["lon"])
        if best_km is None or d < best_km:
            best_km, best = d, p
    if best is None or best_km * 1000 > max_m:
        return None, None
    return round(best_km * 1000), best


def _station_key(name: str) -> str:
    """역명 정규화 - 운영사별 표기차를 흡수해야 환승역이 제대로 묶인다.

    같은 역인데 '왕십리(성동구청)'(서울교통공사) vs '왕십리역'(코레일),
    '디지털미디어시티' vs '디지털미디어시티역'처럼 행마다 다르게 적혀 있어
    완전일치로는 왕십리가 2개 노선으로 잘못 집계됐다(실제 4개).
    괄호 부기와 끝의 '역'을 떼고 비교한다.
    """
    import re
    n = re.sub(r"\(.*?\)", "", name or "").strip()
    return n[:-1] if n.endswith("역") else n


def _station_line_count(subways: list[dict], station: dict) -> int:
    """역의 노선 수(환승 프리미엄용).

    KRIC 데이터는 역×노선이 한 행이라 같은 역이 노선 수만큼 반복된다.
    ⚠ 정규화 이름만으로 묶으면 동명이역(신촌 2호선 vs 신촌 경의선 - 서로 다른
    위치)이 합산되므로, **같은 이름 + 700m 이내** 행들의 서로 다른 노선만 센다
    (환승역은 출구가 넓어 500m 로는 코레일/공사 좌표가 갈릴 수 있음).
    """
    key = _station_key(station["name"])
    lines = set()
    for p in subways:
        if _station_key(p["name"]) != key:
            continue
        if _dist_km(station["lat"], station["lon"], p["lat"], p["lon"]) <= 0.7:
            lines.add(p.get("line") or "?")
    return max(1, len(lines))


def compute_nearest(conn: sqlite3.Connection, refresh: bool = False) -> dict:
    """좌표 보유 단지 × POI 최근접 거리 계산 후 complex 갱신.

    refresh=False 면 poi_fetched_at 이 비어있는(미계산) 단지만 처리(증분).
    """
    subways = [dict(r) for r in conn.execute(
        "SELECT name, line, lat, lon FROM poi WHERE kind='subway'")]
    elems = [dict(r) for r in conn.execute(
        "SELECT name, lat, lon FROM poi WHERE kind='elem'")]
    if not subways and not elems:
        return {"updated": 0, "no_poi": True}

    where = "lat IS NOT NULL AND lon IS NOT NULL"
    if not refresh:
        where += " AND poi_fetched_at IS NULL"
    rows = conn.execute(
        f"SELECT complex_id, lat, lon FROM complex WHERE {where}").fetchall()

    now = _now()
    updated = 0
    for r in rows:
        lat, lon = r["lat"], r["lon"]
        sm, sp = _nearest(lat, lon, subways, SUBWAY_MAX_M)
        swn, swl = None, None
        if sp is not None:
            swl = _station_line_count(subways, sp)
            swn = sp["name"]
            if sp.get("line"):
                swn = f"{sp['name']}·{sp['line']}"
        em, _ = _nearest(lat, lon, elems, SCHOOL_MAX_M)
        conn.execute(
            "UPDATE complex SET subway_m=?, subway_nm=?, subway_lines=?, "
            "school_m=?, poi_fetched_at=? WHERE complex_id=?",
            (sm, swn, swl, em, now, r["complex_id"]),
        )
        updated += 1
    conn.commit()
    return {"updated": updated, "subways": len(subways), "elems": len(elems)}


# ── 학원 밀집도(학군 프록시) ─────────────────────────────────────────────
# 진짜 '학군'(중학교 성취도)은 2017년 전수평가 폐지로 공개 데이터가 없다.
# 카카오 로컬 카테고리 AC5(학원)의 반경 1km 총 개수를 프록시로 쓴다 —
# 대치·중계·목동 학원가가 정량으로 잡힌다(단, 태권도장 등 전 종류 포함 명시).
KAKAO_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
ACADEMY_RADIUS_M = 1000


def collect_academies(conn: sqlite3.Connection, kakao_key: str,
                      limit: int | None = None, refresh: bool = False) -> dict:
    """좌표 보유 단지의 반경 1km 학원 수(meta.total_count 1콜)를 채운다(증분)."""
    where = "lat IS NOT NULL AND lon IS NOT NULL"
    if not refresh:
        where += " AND academy_at IS NULL"
    rows = conn.execute(
        f"SELECT complex_id, lat, lon FROM complex WHERE {where}").fetchall()
    if limit:
        rows = rows[:limit]
    sess = requests.Session()
    sess.headers["Authorization"] = f"KakaoAK {kakao_key}"
    done = failed = 0
    for r in rows:
        cnt = None
        for attempt in range(config.MAX_RETRY):
            try:
                resp = sess.get(KAKAO_CATEGORY_URL, params={
                    "category_group_code": "AC5",
                    "x": r["lon"], "y": r["lat"],
                    "radius": ACADEMY_RADIUS_M, "size": 1,
                }, timeout=config.REQUEST_TIMEOUT)
                if resp.status_code == 429:          # 쿼터 초과 - 잠시 대기
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                cnt = (resp.json().get("meta") or {}).get("total_count")
                break
            except (requests.RequestException, ValueError):
                time.sleep(2 ** attempt)
        if cnt is None:
            failed += 1        # academy_at 미기록 → 다음 실행에서 자동 재시도
            continue
        conn.execute(
            "UPDATE complex SET academy_cnt=?, academy_at=? WHERE complex_id=?",
            (int(cnt), _now(), r["complex_id"]))
        done += 1
        if done % 500 == 0:
            conn.commit()
        time.sleep(config.REQUEST_SLEEP)
    conn.commit()
    return {"academies": done, "failed": failed, "remaining": len(rows) - done - failed}


def run(conn: sqlite3.Connection, refresh: bool = False,
        kakao_key: str | None = None, academy_limit: int | None = None) -> dict:
    """CLI 진입점: CSV 적재 → 최근접 계산 → (키 있으면) 학원 밀집도 수집."""
    loaded = load_poi(conn)
    nearest = compute_nearest(conn, refresh=refresh)
    academy = None
    if kakao_key:
        academy = collect_academies(conn, kakao_key, limit=academy_limit,
                                    refresh=refresh)
    return {"loaded": loaded, "nearest": nearest, "academy": academy}
