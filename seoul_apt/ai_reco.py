"""Gemini 무료 티어로 주간 물건 추천 코멘트 생성(best-effort).

reco.py 가 만든 후보 JSON(수치 근거)을 Gemini 에 주고 정성 평가만 맡긴다.
GEMINI_API_KEY 가 없거나 호출이 실패해도 파이프라인을 막지 않는다.
"""

import json

import requests

from . import config

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent")
# ⚠2.0-flash는 신규 키에서 무료 쿼터 0(429) — 2026-08-01 교체
MODEL = "gemini-3.5-flash"
TIMEOUT = 60

PROMPT = """당신은 서울 아파트 시장 분석가입니다. 아래는 최근 4주 실거래 중
정량 기준(단지 1년 평단가 대비 저가 거래, 전세가율 등)으로 선별된 후보 목록입니다.

이 중 주목할 만한 물건 3~5개를 골라 한국어로 추천해 주세요. 각 물건마다:
- 한 줄 요약(단지·면적·거래가)
- 추천 근거(제공된 수치만 사용: 저가폭, 전세가율, 고점대비, 거래량)
- 유의할 리스크(저층/급매 가능성, 표본 부족 등 데이터 한계 포함)

과장 없이 간결하게. 마지막에 "본 내용은 실거래 통계 기반 참고자료이며
투자 판단의 책임은 본인에게 있습니다." 문구를 넣으세요.

후보 데이터(JSON):
{data}
"""


def gemini_generate(prompt: str, api_key: str, model: str = MODEL) -> str:
    url = GEMINI_URL.format(model=model)
    resp = requests.post(
        url, params={"key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"maxOutputTokens": 2048,
                                   "thinkingConfig": {"thinkingBudget": 0}}},
        timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def weekly_recommendation(reco_path=None) -> str | None:
    """후보 JSON → Gemini 추천 텍스트. 실패/키없음 시 None."""
    reco_path = reco_path or config.RECO_PATH
    if not reco_path.exists():
        print("[aireco] 후보 파일 없음 - 먼저 `reco` 를 실행하세요")
        return None
    api_key = config.get_key(config.ENV_GEMINI, required=False)
    if not api_key:
        print("[aireco] GEMINI_API_KEY 없음 - 건너뜀")
        return None
    payload = json.loads(reco_path.read_text(encoding="utf-8"))
    if not payload.get("candidates"):
        print("[aireco] 후보 0건 - 건너뜀")
        return None
    prompt = PROMPT.format(data=json.dumps(payload, ensure_ascii=False))
    try:
        return gemini_generate(prompt, api_key)
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"[aireco] Gemini 호출 실패(무시): {e}")
        return None
