"""SQLite 스키마 및 멱등 upsert 헬퍼.

모든 거래 INSERT 는 UNIQUE 제약 + INSERT OR IGNORE 로 멱등이므로
같은 월을 여러 번 재수집해도 중복이 쌓이지 않는다.
"""

import re
import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS district (
    lawd_cd  TEXT PRIMARY KEY,
    name_ko  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS complex (
    complex_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    lawd_cd      TEXT NOT NULL REFERENCES district(lawd_cd),
    umd_nm       TEXT,              -- 법정동
    apt_nm       TEXT NOT NULL,     -- 단지명(원본)
    apt_nm_norm  TEXT NOT NULL,     -- 단지명(정규화)
    build_year   INTEGER,
    jibun        TEXT,
    lat          REAL,              -- 지오코딩 결과
    lon          REAL,
    geocoded_at  TEXT,
    UNIQUE(lawd_cd, umd_nm, apt_nm_norm, build_year)
);

CREATE TABLE IF NOT EXISTS sale_txn (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complex_id    INTEGER NOT NULL REFERENCES complex(complex_id),
    deal_date     TEXT NOT NULL,      -- 'YYYY-MM-DD'
    exclu_area    REAL NOT NULL,
    floor         INTEGER,
    amount_manwon INTEGER NOT NULL,   -- 거래금액(만원)
    canceled      INTEGER NOT NULL DEFAULT 0,  -- 계약해제 여부(1=해제)
    cancel_date   TEXT,               -- 해제사유발생일 'YYYY-MM-DD'
    deal_gbn      TEXT,               -- 거래유형(중개거래/직거래)
    UNIQUE(complex_id, deal_date, exclu_area, floor, amount_manwon)
);

CREATE TABLE IF NOT EXISTS rent_txn (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    complex_id     INTEGER NOT NULL REFERENCES complex(complex_id),
    deal_date      TEXT NOT NULL,
    exclu_area     REAL NOT NULL,
    floor          INTEGER,
    deposit_manwon INTEGER NOT NULL,  -- 보증금(만원)
    monthly_manwon INTEGER NOT NULL,  -- 월세(만원), 0 => 전세
    rent_type      TEXT NOT NULL,     -- 'jeonse' | 'wolse'
    UNIQUE(complex_id, deal_date, exclu_area, floor, deposit_manwon, monthly_manwon)
);

CREATE TABLE IF NOT EXISTS gongsi_price (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complex_id    INTEGER REFERENCES complex(complex_id),
    year          INTEGER NOT NULL,
    exclu_area    REAL,
    price_manwon  INTEGER NOT NULL,   -- 공시가격(만원)
    match_conf    REAL DEFAULT 1.0,
    UNIQUE(complex_id, year, exclu_area)
);

CREATE TABLE IF NOT EXISTS reb_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    region      TEXT NOT NULL,        -- '서울' 또는 자치구명
    stat_name   TEXT NOT NULL,        -- 지표명(매매가격지수 등)
    period      TEXT NOT NULL,        -- 'YYYY-MM'
    value       REAL,
    UNIQUE(region, stat_name, period)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    lawd_cd     TEXT NOT NULL,
    deal_ymd    TEXT NOT NULL,        -- 'YYYYMM'
    kind        TEXT NOT NULL,        -- 'sale' | 'rent'
    fetched_at  TEXT NOT NULL,
    row_count   INTEGER,
    PRIMARY KEY (lawd_cd, deal_ymd, kind)
);

CREATE INDEX IF NOT EXISTS idx_sale_complex_date ON sale_txn(complex_id, deal_date);
CREATE INDEX IF NOT EXISTS idx_rent_complex_date ON rent_txn(complex_id, deal_date);
CREATE INDEX IF NOT EXISTS idx_complex_lawd ON complex(lawd_cd);
"""


def normalize_apt_name(name: str) -> str:
    """단지명 정규화 - 공백/괄호/특수문자 제거로 표기 흔들림 흡수."""
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r"\(.*?\)", "", s)          # 괄호 내용 제거
    s = re.sub(r"[\s\-_·,]", "", s)        # 공백·구분자 제거
    return s


def connect(db_path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    """DB 연결 후 스키마 보장."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")  # 동시 실행 시 락 대기(ms)
    conn.executescript(SCHEMA)
    _migrate(conn)
    _seed_districts(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """구버전 DB에 없는 컬럼을 추가한다(멱등)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sale_txn)")}
    if "canceled" not in cols:
        conn.execute("ALTER TABLE sale_txn ADD COLUMN canceled INTEGER NOT NULL DEFAULT 0")
    if "cancel_date" not in cols:
        conn.execute("ALTER TABLE sale_txn ADD COLUMN cancel_date TEXT")
    if "deal_gbn" not in cols:
        conn.execute("ALTER TABLE sale_txn ADD COLUMN deal_gbn TEXT")
    conn.commit()


def _seed_districts(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO district(lawd_cd, name_ko) VALUES (?, ?)",
        list(config.SEOUL_DISTRICTS.items()),
    )
    conn.commit()


def upsert_complex(conn, lawd_cd, umd_nm, apt_nm, build_year, jibun) -> int:
    """단지를 upsert 하고 complex_id 반환."""
    norm = normalize_apt_name(apt_nm)
    conn.execute(
        """INSERT OR IGNORE INTO complex
           (lawd_cd, umd_nm, apt_nm, apt_nm_norm, build_year, jibun)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (lawd_cd, umd_nm, apt_nm, norm, build_year, jibun),
    )
    row = conn.execute(
        """SELECT complex_id FROM complex
           WHERE lawd_cd=? AND umd_nm IS ? AND apt_nm_norm=? AND build_year IS ?""",
        (lawd_cd, umd_nm, norm, build_year),
    ).fetchone()
    return row["complex_id"]


def insert_sale(conn, complex_id, deal_date, exclu_area, floor, amount_manwon,
                canceled=0, cancel_date=None, deal_gbn=None) -> None:
    """매매 거래 upsert.

    같은 거래가 나중에 계약해제로 재수집되면 canceled/cancel_date 를 갱신해야
    하므로 INSERT OR IGNORE 가 아니라 ON CONFLICT DO UPDATE 를 쓴다.
    """
    conn.execute(
        """INSERT INTO sale_txn
           (complex_id, deal_date, exclu_area, floor, amount_manwon,
            canceled, cancel_date, deal_gbn)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(complex_id, deal_date, exclu_area, floor, amount_manwon)
           DO UPDATE SET
             canceled=excluded.canceled,
             cancel_date=excluded.cancel_date,
             deal_gbn=COALESCE(excluded.deal_gbn, sale_txn.deal_gbn)""",
        (complex_id, deal_date, exclu_area, floor, amount_manwon,
         int(canceled), cancel_date, deal_gbn),
    )


def insert_rent(conn, complex_id, deal_date, exclu_area, floor,
                deposit_manwon, monthly_manwon) -> None:
    rent_type = "wolse" if monthly_manwon and monthly_manwon > 0 else "jeonse"
    conn.execute(
        """INSERT OR IGNORE INTO rent_txn
           (complex_id, deal_date, exclu_area, floor, deposit_manwon,
            monthly_manwon, rent_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (complex_id, deal_date, exclu_area, floor, deposit_manwon,
         monthly_manwon, rent_type),
    )


def insert_gongsi(conn, complex_id, year, exclu_area, price_manwon,
                  match_conf=1.0) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO gongsi_price
           (complex_id, year, exclu_area, price_manwon, match_conf)
           VALUES (?, ?, ?, ?, ?)""",
        (complex_id, year, exclu_area, price_manwon, match_conf),
    )


def insert_reb(conn, region, stat_name, period, value) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO reb_index (region, stat_name, period, value)
           VALUES (?, ?, ?, ?)""",
        (region, stat_name, period, value),
    )


def record_fetch(conn, lawd_cd, deal_ymd, kind, fetched_at, row_count) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO fetch_log
           (lawd_cd, deal_ymd, kind, fetched_at, row_count)
           VALUES (?, ?, ?, ?, ?)""",
        (lawd_cd, deal_ymd, kind, fetched_at, row_count),
    )


def already_fetched(conn, lawd_cd, deal_ymd, kind) -> bool:
    row = conn.execute(
        "SELECT 1 FROM fetch_log WHERE lawd_cd=? AND deal_ymd=? AND kind=?",
        (lawd_cd, deal_ymd, kind),
    ).fetchone()
    return row is not None


def complexes_without_coords(conn, lawd_cd: str | None = None) -> list[sqlite3.Row]:
    """좌표가 아직 없는 단지 목록(지오코딩 대상)."""
    q = "SELECT * FROM complex WHERE lat IS NULL"
    args: tuple = ()
    if lawd_cd:
        q += " AND lawd_cd=?"
        args = (lawd_cd,)
    return conn.execute(q, args).fetchall()


def set_coords(conn, complex_id, lat, lon, geocoded_at) -> None:
    conn.execute(
        "UPDATE complex SET lat=?, lon=?, geocoded_at=? WHERE complex_id=?",
        (lat, lon, geocoded_at, complex_id),
    )
