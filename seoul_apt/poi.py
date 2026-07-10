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
from datetime import datetime, timezone
from pathlib import Path

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
        swn = None
        if sp is not None:
            swn = sp["name"]
            if sp.get("line"):
                swn = f"{sp['name']}·{sp['line']}"
        em, _ = _nearest(lat, lon, elems, SCHOOL_MAX_M)
        conn.execute(
            "UPDATE complex SET subway_m=?, subway_nm=?, school_m=?, "
            "poi_fetched_at=? WHERE complex_id=?",
            (sm, swn, em, now, r["complex_id"]),
        )
        updated += 1
    conn.commit()
    return {"updated": updated, "subways": len(subways), "elems": len(elems)}


def run(conn: sqlite3.Connection, refresh: bool = False) -> dict:
    """CLI 진입점: CSV 적재 → 최근접 계산."""
    loaded = load_poi(conn)
    nearest = compute_nearest(conn, refresh=refresh)
    return {"loaded": loaded, "nearest": nearest}
