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

CREATE TABLE IF NOT EXISTS subscription (
    house_manage_no TEXT PRIMARY KEY, -- 청약홈 주택관리번호
    pblanc_no       TEXT,             -- 공고번호
    kind            TEXT NOT NULL,    -- 'apt' | 'remndr'(무순위/잔여) | 'optn'(임의공급)
    secd_nm         TEXT,             -- 공급유형(무순위/불법행위 재공급/임의공급 등, API HOUSE_SECD_NM)
    house_nm        TEXT NOT NULL,    -- 주택명
    adres           TEXT,             -- 공급위치 주소
    tot_suply       INTEGER,          -- 공급규모(세대)
    rcrit_de        TEXT,             -- 모집공고일 'YYYY-MM-DD'
    rcept_bgnde     TEXT,             -- 청약접수 시작
    rcept_endde     TEXT,             -- 청약접수 종료
    przwner_de      TEXT,             -- 당첨자발표일
    cntrct_bgnde    TEXT,             -- 계약 시작
    cntrct_endde    TEXT,             -- 계약 종료
    mvn_ym          TEXT,             -- 입주예정월 'YYYYMM'
    cnstrct_nm      TEXT,             -- 시공사
    url             TEXT,             -- 공고 상세 URL
    lat             REAL,
    lon             REAL,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS subscription_model (
    house_manage_no TEXT NOT NULL REFERENCES subscription(house_manage_no),
    house_ty        TEXT NOT NULL,    -- 주택형(예: 084.9800A)
    suply_ar        REAL,             -- 공급면적(㎡)
    suply_hshldco   INTEGER,          -- 일반공급 세대수
    spsply_hshldco  INTEGER,          -- 특별공급 세대수
    top_amount      INTEGER,          -- 분양최고금액(만원)
    PRIMARY KEY (house_manage_no, house_ty)
);

CREATE TABLE IF NOT EXISTS poi (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    kind   TEXT NOT NULL,             -- 'subway' | 'elem'
    name   TEXT NOT NULL,             -- 역명 / 학교명
    line   TEXT,                      -- 노선명(지하철), 학교는 NULL
    lat    REAL NOT NULL,
    lon    REAL NOT NULL,
    UNIQUE(kind, name, lat, lon)
);

CREATE TABLE IF NOT EXISTS listing (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,      -- 'naver' | 'zigbang'
    item_id        TEXT NOT NULL,      -- 매물 고유번호(대표매물 articleNumber 등)
    complex_id     INTEGER REFERENCES complex(complex_id),
    trade_type     TEXT NOT NULL,      -- 'sale' | 'jeonse' | 'wolse'
    price_manwon   INTEGER,            -- 매매가/보증금(만원)
    monthly_manwon INTEGER,            -- 월세(만원), 0/NULL이면 전세·매매
    area_m2        REAL,               -- 전용면적(㎡)
    floor          INTEGER,            -- 해당 층
    floor_total    INTEGER,            -- 총 층
    dong           TEXT,               -- 동 이름
    direction      TEXT,               -- 향(정규화: 남/남동 등)
    description     TEXT,              -- 매물 설명(중개사 코멘트)
    confirm_date   TEXT,               -- 매물 확인일 'YYYY-MM-DD'
    url            TEXT,               -- 매물 상세 링크
    first_seen     TEXT NOT NULL,      -- 최초 수집 시각
    last_seen      TEXT NOT NULL,      -- 마지막 수집 시각
    status         TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'gone'(내려감)
    UNIQUE(source, item_id)
);

CREATE INDEX IF NOT EXISTS idx_listing_complex ON listing(complex_id, trade_type);

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
    # 건축물대장 부가정보(단지 단위)
    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(complex)")}
    for name, decl in [
        ("households", "INTEGER"),       # 세대수
        ("far", "REAL"),                 # 용적률(%)
        ("bcr", "REAL"),                 # 건폐율(%)
        ("approval_date", "TEXT"),       # 사용승인일 'YYYY-MM-DD'
        ("bldg_fetched_at", "TEXT"),     # 건축물대장 조회 시각(재조회 skip용)
        # 입지 레이어(역세권·초품아) — 최근접 POI 거리(m)와 이름
        ("subway_m", "INTEGER"),         # 최근접 지하철역 직선거리(m)
        ("subway_nm", "TEXT"),           # 최근접 역명(+노선)
        ("school_m", "INTEGER"),         # 최근접 초등학교 직선거리(m)
        ("poi_fetched_at", "TEXT"),      # POI 최근접 계산 시각(증분 skip용)
        # 매물(네이버·직방) 단지번호 매핑 캐시(1회 매칭 후 재사용)
        ("naver_no", "TEXT"),            # 네이버부동산 complexNo
        ("zigbang_id", "INTEGER"),       # 직방 danji id
        ("listing_matched_at", "TEXT"),  # 매물 단지 매칭 시각(재매칭 skip용)
    ]:
        if name not in ccols:
            conn.execute(f"ALTER TABLE complex ADD COLUMN {name} {decl}")
    # 청약 공급유형(무순위/불법행위 재공급/임의공급 구분)
    scols = {r["name"] for r in conn.execute("PRAGMA table_info(subscription)")}
    if "secd_nm" not in scols:
        conn.execute("ALTER TABLE subscription ADD COLUMN secd_nm TEXT")
    # 경쟁률은 마감된 공고에만 존재 - 지난 청약을 보관하지 않기로 해 함께 폐기
    conn.execute("DROP TABLE IF EXISTS subscription_cmpet")
    # 임의공급 오퍼레이션이 'YYYYMMDD'로 주던 날짜를 'YYYY-MM-DD'로 통일.
    # 섞여 있으면 문자열 비교가 뒤집혀 마감 공고가 걸러지지 않는다(사고 이력).
    for c in ("rcrit_de", "rcept_bgnde", "rcept_endde", "przwner_de",
              "cntrct_bgnde", "cntrct_endde"):
        conn.execute(
            f"UPDATE subscription SET {c} = "
            f"substr({c},1,4)||'-'||substr({c},5,2)||'-'||substr({c},7,2) "
            f"WHERE {c} IS NOT NULL AND length({c})=8 AND {c} NOT LIKE '%-%'")
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


def complexes_without_building(conn, lawd_cd: str | None = None,
                               limit: int | None = None) -> list[sqlite3.Row]:
    """건축물대장 정보가 아직 없는 단지(지번 있는 것만) - 조회 대상."""
    q = ("SELECT complex_id, lawd_cd, umd_nm, apt_nm, jibun FROM complex "
         "WHERE bldg_fetched_at IS NULL AND jibun IS NOT NULL")
    args: list = []
    if lawd_cd:
        q += " AND lawd_cd=?"
        args.append(lawd_cd)
    q += " ORDER BY complex_id"
    if limit:
        q += " LIMIT ?"
        args.append(limit)
    return conn.execute(q, args).fetchall()


def set_building(conn, complex_id, households, far, bcr, approval_date,
                 fetched_at) -> None:
    conn.execute(
        "UPDATE complex SET households=?, far=?, bcr=?, approval_date=?, "
        "bldg_fetched_at=? WHERE complex_id=?",
        (households, far, bcr, approval_date, fetched_at, complex_id),
    )


# ── 청약·분양 ────────────────────────────────────────────────────────────
def upsert_subscription(conn, s: dict) -> None:
    """분양공고 upsert. 일정 변경(접수일 연기 등)이 재수집 시 반영되도록
    좌표를 제외한 필드는 항상 최신값으로 갱신한다."""
    conn.execute(
        """INSERT INTO subscription
           (house_manage_no, pblanc_no, kind, secd_nm, house_nm, adres, tot_suply,
            rcrit_de, rcept_bgnde, rcept_endde, przwner_de,
            cntrct_bgnde, cntrct_endde, mvn_ym, cnstrct_nm, url, fetched_at)
           VALUES (:house_manage_no, :pblanc_no, :kind, :secd_nm, :house_nm, :adres,
                   :tot_suply, :rcrit_de, :rcept_bgnde, :rcept_endde,
                   :przwner_de, :cntrct_bgnde, :cntrct_endde, :mvn_ym,
                   :cnstrct_nm, :url, :fetched_at)
           ON CONFLICT(house_manage_no) DO UPDATE SET
             pblanc_no=excluded.pblanc_no, kind=excluded.kind,
             secd_nm=excluded.secd_nm,
             house_nm=excluded.house_nm, adres=excluded.adres,
             tot_suply=excluded.tot_suply, rcrit_de=excluded.rcrit_de,
             rcept_bgnde=excluded.rcept_bgnde, rcept_endde=excluded.rcept_endde,
             przwner_de=excluded.przwner_de, cntrct_bgnde=excluded.cntrct_bgnde,
             cntrct_endde=excluded.cntrct_endde, mvn_ym=excluded.mvn_ym,
             cnstrct_nm=excluded.cnstrct_nm, url=excluded.url,
             fetched_at=excluded.fetched_at""",
        s,
    )


def upsert_subscription_model(conn, m: dict) -> None:
    conn.execute(
        """INSERT INTO subscription_model
           (house_manage_no, house_ty, suply_ar, suply_hshldco,
            spsply_hshldco, top_amount)
           VALUES (:house_manage_no, :house_ty, :suply_ar, :suply_hshldco,
                   :spsply_hshldco, :top_amount)
           ON CONFLICT(house_manage_no, house_ty) DO UPDATE SET
             suply_ar=excluded.suply_ar, suply_hshldco=excluded.suply_hshldco,
             spsply_hshldco=excluded.spsply_hshldco,
             top_amount=excluded.top_amount""",
        m,
    )


def purge_past_subscriptions(conn, today: str) -> int:
    """접수가 끝난 공고와 그 주택형을 삭제. 삭제한 공고 수 반환.

    청약은 접수 가능한 건만 의미가 있어 마감분은 보관하지 않는다. 원천이
    청약홈 API라 필요하면 언제든 다시 받을 수 있다(종료일 NULL은 일정 미확정
    이므로 보존).
    """
    conn.execute(
        """DELETE FROM subscription_model WHERE house_manage_no IN
           (SELECT house_manage_no FROM subscription
            WHERE rcept_endde IS NOT NULL AND rcept_endde < ?)""", (today,))
    cur = conn.execute(
        "DELETE FROM subscription "
        "WHERE rcept_endde IS NOT NULL AND rcept_endde < ?", (today,))
    return cur.rowcount or 0


def subscriptions_without_coords(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT house_manage_no, house_nm, adres FROM subscription "
        "WHERE lat IS NULL AND adres IS NOT NULL").fetchall()


def set_subscription_coords(conn, house_manage_no, lat, lon) -> None:
    conn.execute(
        "UPDATE subscription SET lat=?, lon=? WHERE house_manage_no=?",
        (lat, lon, house_manage_no),
    )
