"""서울 아파트 추적기 설정 - 지역코드, 경로, 상수."""

import os
from pathlib import Path

# ── 경로 ────────────────────────────────────────────────────────────────
PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "seoul_apt.sqlite"

DOCS_DIR = REPO_ROOT / "docs"
EXPORT_DIR = DOCS_DIR / "data"
GONGSI_DIR = DATA_DIR / "gongsi"  # 공시가격 대량 파일을 놓는 위치

WATCHLIST_PATH = REPO_ROOT / "config" / "watchlist.yml"
NOTIFY_STATE_PATH = DATA_DIR / "notify_state.json"
RECO_PATH = DATA_DIR / "reco_candidates.json"

# ── 서울 25개 자치구 법정동코드(시군구 5자리) ────────────────────────────
# 출처: 행정표준코드관리시스템(code.go.kr) 법정동코드 앞 5자리
SEOUL_DISTRICTS = {
    "11110": "종로구",
    "11140": "중구",
    "11170": "용산구",
    "11200": "성동구",
    "11215": "광진구",
    "11230": "동대문구",
    "11260": "중랑구",
    "11290": "성북구",
    "11305": "강북구",
    "11320": "도봉구",
    "11350": "노원구",
    "11380": "은평구",
    "11410": "서대문구",
    "11440": "마포구",
    "11470": "양천구",
    "11500": "강서구",
    "11530": "구로구",
    "11545": "금천구",
    "11560": "영등포구",
    "11590": "동작구",
    "11620": "관악구",
    "11650": "서초구",
    "11680": "강남구",
    "11710": "송파구",
    "11740": "강동구",
}

# ── 수집 파라미터 ────────────────────────────────────────────────────────
# 국토부 실거래가 API 제공 최초 시점: 매매 2006-01, 전월세 2011-01
BACKFILL_START_YM = "200601"       # 백필 시작 계약년월 (매매 최장기간)
RENT_START_YM = "201101"           # 전월세는 2011-01 이전 데이터가 없어 그 전 월은 조회 생략
DAILY_LOOKBACK_MONTHS = 3          # 일일 수집 시 재수집할 최근 개월 수(신고 지연/정정 대응)
NUM_OF_ROWS = 1000                 # API 페이지당 행 수
MIN_MONTH_SAMPLE = 10              # 구 대표값·랭킹에 쓸 월의 최소 매매 표본(부분월/희소월 제외)
REQUEST_TIMEOUT = 30               # 초
REQUEST_SLEEP = 0.12               # 호출 사이 대기(속도제한 완화)
MAX_RETRY = 4                      # 네트워크 오류 재시도 횟수

# ── 전용면적 버킷(㎡) ────────────────────────────────────────────────────
# 라벨은 프런트 표시에 사용. (하한, 상한(미만)) None은 무한.
AREA_BUCKETS = [
    ("~60㎡", 0.0, 60.0),
    ("60~85㎡", 60.0, 85.0),
    ("85~135㎡", 85.0, 135.0),
    ("135㎡~", 135.0, None),
]

# 평 환산(1평 = 3.305785㎡)
PYEONG_PER_SQM = 1 / 3.305785


def area_bucket(exclu_area: float) -> str:
    """전용면적(㎡)을 표준 버킷 라벨로 변환."""
    for label, lo, hi in AREA_BUCKETS:
        if exclu_area >= lo and (hi is None or exclu_area < hi):
            return label
    return AREA_BUCKETS[-1][0]


# ── 환경변수 키 이름 ─────────────────────────────────────────────────────
ENV_DATA_GO_KR = "DATA_GO_KR_KEY"
ENV_REB = "REB_API_KEY"
ENV_KAKAO_REST = "KAKAO_REST_KEY"
ENV_KAKAO_JS = "KAKAO_JS_KEY"
ENV_TG_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_TG_CHAT = "TELEGRAM_CHAT_ID"
ENV_GEMINI = "GEMINI_API_KEY"


def get_key(env_name: str, required: bool = True) -> str | None:
    """환경변수에서 키를 읽는다. 필수인데 없으면 예외."""
    val = os.environ.get(env_name)
    if val:
        return val.strip()
    if required:
        raise RuntimeError(
            f"환경변수 {env_name} 가 설정되지 않았습니다. "
            f".env 파일 또는 GitHub Secrets 에 등록하세요."
        )
    return None
