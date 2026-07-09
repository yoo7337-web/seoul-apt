"""공동주택 공시가격 적재 - 연 1회 공개 대량 파일 파서 + 단지 매칭.

공시가격은 별도 API 키 없이 data.go.kr 등에서 내려받은 대량 파일
(CSV/XLSX)을 data/gongsi/ 에 두면 이 모듈이 읽어 적재한다.
연도별로 컬럼명·인코딩이 달라지므로 헤더를 유연하게 매칭한다.
"""

import re
from pathlib import Path

import pandas as pd

from . import config, db

# 헤더 후보(부분 일치) → 표준 필드
COLUMN_HINTS = {
    "sido": ["시도", "광역"],
    "sigungu": ["시군구"],
    "umd": ["읍면동", "법정동", "동명"],
    "apt": ["단지", "공동주택명", "아파트", "건물명"],
    "area": ["전용면적", "면적"],
    "price": ["공시가격", "공동주택가격", "가격"],
    "year": ["기준연도", "기준년도", "공시기준", "연도"],
}

NAME_TO_LAWD = {name: code for code, name in config.SEOUL_DISTRICTS.items()}


def _find_col(columns: list[str], field: str) -> str | None:
    for col in columns:
        c = str(col).replace(" ", "")
        for hint in COLUMN_HINTS[field]:
            if hint in c:
                return col
    return None


def _read_any(path: Path) -> pd.DataFrame | None:
    """CSV/XLSX 를 인코딩 관대하게 읽는다."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        try:
            return pd.read_excel(path, dtype=str)
        except Exception:
            return None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
        except Exception:
            return None
    return None


def _to_year(val: str, fallback: int | None) -> int | None:
    m = re.search(r"(20\d{2})", str(val))
    if m:
        return int(m.group(1))
    return fallback


def load_gongsi_files(conn, gongsi_dir: Path = config.GONGSI_DIR) -> int:
    """gongsi_dir 의 모든 파일을 적재. 매칭·삽입한 row 수 반환."""
    gongsi_dir = Path(gongsi_dir)
    if not gongsi_dir.exists():
        return 0

    total = 0
    for path in sorted(gongsi_dir.iterdir()):
        if path.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            continue
        df = _read_any(path)
        if df is None or df.empty:
            continue
        total += _ingest_frame(conn, df, default_year=_to_year(path.stem, None))
        conn.commit()
    return total


def _ingest_frame(conn, df: pd.DataFrame, default_year: int | None) -> int:
    cols = list(df.columns)
    c_sigungu = _find_col(cols, "sigungu")
    c_apt = _find_col(cols, "apt")
    c_price = _find_col(cols, "price")
    if not (c_sigungu and c_apt and c_price):
        return 0
    c_umd = _find_col(cols, "umd")
    c_area = _find_col(cols, "area")
    c_year = _find_col(cols, "year")

    inserted = 0
    for _, r in df.iterrows():
        sigungu = str(r.get(c_sigungu, "")).strip()
        gu = _match_gu(sigungu)
        if not gu:
            continue
        lawd_cd = NAME_TO_LAWD[gu]
        apt_nm = str(r.get(c_apt, "")).strip()
        if not apt_nm:
            continue
        price = _parse_price(r.get(c_price))
        if price is None:
            continue
        area = _parse_float(r.get(c_area)) if c_area else None
        year = _to_year(r.get(c_year), default_year) if c_year else default_year
        if year is None:
            continue

        complex_id, conf = _match_complex(conn, lawd_cd, apt_nm,
                                          str(r.get(c_umd, "")).strip() if c_umd else None)
        if complex_id is None:
            continue
        db.insert_gongsi(conn, complex_id, year, area, price, conf)
        inserted += 1
    return inserted


def _match_gu(sigungu: str) -> str | None:
    """시군구 문자열에서 서울 자치구명을 추출.

    R-ONE 지역필터와 같은 부분일치(in) 버그를 방지한다: '중구' 등이 substring
    으로 '인천광역시 중구'·'대구광역시 중구'에도 매칭돼 타시도 공시가격이 서울
    단지에 잘못 배정되는 사고 이력. '서울'이 포함된 행만 대상으로 하고,
    자치구명은 공백/쉼표 토큰 단위로 정확히 일치할 때만 인정한다.
    """
    if "서울" not in sigungu:
        return None
    tokens = sigungu.replace(",", " ").split()
    for g in NAME_TO_LAWD:
        if g in tokens:
            return g
    return None


def _match_complex(conn, lawd_cd, apt_nm, umd):
    """정규화 단지명으로 complex 매칭. (complex_id, match_conf) 반환."""
    norm = db.normalize_apt_name(apt_nm)
    if umd:
        row = conn.execute(
            """SELECT complex_id FROM complex
               WHERE lawd_cd=? AND apt_nm_norm=? AND umd_nm=?""",
            (lawd_cd, norm, umd),
        ).fetchone()
        if row:
            return row["complex_id"], 1.0
    row = conn.execute(
        "SELECT complex_id FROM complex WHERE lawd_cd=? AND apt_nm_norm=?",
        (lawd_cd, norm),
    ).fetchone()
    if row:
        return row["complex_id"], 0.8
    return None, 0.0


def _parse_price(val) -> int | None:
    """공시가격(원) → 만원 정수."""
    if val is None:
        return None
    t = re.sub(r"[^\d]", "", str(val))
    if not t:
        return None
    won = int(t)
    return won // 10000 if won >= 10000 else won  # 이미 만원 단위면 그대로


def _parse_float(val) -> float | None:
    if val is None:
        return None
    t = re.sub(r"[^\d.]", "", str(val))
    try:
        return float(t) if t else None
    except ValueError:
        return None
