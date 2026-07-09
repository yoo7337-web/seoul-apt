# seoul-apt — Claude 작업 지침

서울 아파트 실거래가 수집 + 카카오지도 정적사이트 + 텔레그램 알림/AI 추천.
파이썬: `.venv\Scripts\python.exe` 사용 (Windows). 실행 시 `PYTHONIOENCODING=utf-8` 권장.

## 구조 요약
- `seoul_apt/` 수집·집계·export·알림·추천 (CLI: `python -m seoul_apt.cli <cmd>`)
- `docs/` 카카오지도 정적사이트 (GitHub Pages, main `/docs`)
- `config/watchlist.yml` 관심지역 워치리스트 (알림·추천 대상)
- `data/seoul_apt.sqlite` 누적 DB(커밋됨), `data/notify_state.json` 알림 상태
- GitHub Actions: daily(09:00 KST 수집+알림), weekly(일 10:30 KST AI 추천)
- 로컬 미리보기: launch.json `seoul-apt-docs` → http://localhost:8511

## ⭐ 트리거: "아파트 추천해줘" / "관심구 물건 추천" / "물건 추천"

사용자가 위와 같이 말하면 = **내가(Claude) 직접 후보를 분석해 추천**하라는 뜻.
Gemini 주간 자동추천과 별개로, 구독 Claude를 활용한 수동 큐레이션이다. 순서:

1. **후보 선별 실행** (수치 근거 생성):
   ```
   .venv\Scripts\python.exe -m seoul_apt.cli reco
   ```
   → `data/reco_candidates.json` 생성 (관심 구의 최근 4주 저평가 후보 + 근거 수치)

2. **`data/reco_candidates.json` 을 Read** 해서 후보를 파악한다.
   각 후보의 수치: discount_pct(1년 평단가 대비), jeonse_ratio(전세가율),
   drop_from_peak_pct(고점대비), volume_x_3m(거래량 배율), sale_count_1y(표본).

3. **3~5개를 골라 정성 분석**한다. 원칙:
   - 제공된 수치만 근거로 사용(외부 시세 추측 금지)
   - 물건마다: 한 줄 요약 / 추천 근거 / 리스크(저층·급매 가능성, 표본 부족 등)
   - 표본(sale_count_1y)이 10건 미만이면 반드시 신뢰도 경고
   - 말미에 "실거래 통계 기반 참고자료, 투자 판단 책임은 본인" 문구

4. **화면 출력 후 사용자가 원하면 텔레그램 발송**:
   `.env`의 TELEGRAM_BOT_TOKEN/CHAT_ID 로 `notify.send_telegram()` 사용.

## 주의사항
- 알림 상태(`data/notify_state.json`)는 Actions가 관리 — 로컬에서 `alerts`를
  실발송으로 돌리면 상태가 갱신돼 다음 자동발송에서 그 구간이 빠진다.
  로컬 확인은 반드시 `alerts --dry-run`.
- 해제(취소)거래는 `sale_txn.canceled=1` — 모든 통계·추천에서 제외돼 있다.
  새 쿼리를 쓸 때도 `canceled=0` 필터를 잊지 말 것.
- 랭킹/대표값은 부분월 왜곡 방지용 `aggregate.representative_months()`(표본≥10)를 쓴다.
- REB(부동산원)는 `SttsApiTblData.do` 엔드포인트 + STATBL_ID
  매매 `A_2024_00178` / 전세 `A_2024_00182` (표 메타용 `SttsApiTbl.do` 아님).
- `.env`는 gitignore. `docs/js/config.js`에 카카오 JS 키가 주입되는데 이는
  도메인 제한이 걸린 공개용 키라 Actions가 커밋해도 무방(다른 키는 절대 커밋 금지).
- 청약·분양(`subscription` 명령)은 data.go.kr **청약홈 API 2종 활용신청 승인**이
  필요(분양정보 15098547, 경쟁률 15098905 — 기존 DATA_GO_KR_KEY 그대로).
  미승인이면 401 로그만 남기고 건너뛴다. 필드명 확인은 `subscription --debug`.
- **가격 비교는 반드시 같은 크기·같은 시기**: 전세가율·안전마진·급매·주변시세는
  전용면적 ±12% + 최근 1~2년으로 한정해 매칭. 전 평형 혼합 중앙값 금지
  (한남더힐 전세가율 26%, 오피스텔 300% 왜곡 사고 이력).
- **평형 구분 UI는 4개 버킷 정확 선택만**: 임의 연속 범위(평 슬라이더)를 버킷과
  겹침으로 매칭하면 4평이 18~26평 검색에 걸리는 오류 발생(사고 이력).
- **R-ONE 지역 필터는 `region.startswith("서울")`**: 부분일치는 '인천>중구' 등
  타시도가 혼입된다(사고 이력).
- **docs/js·css 수정 시 index.html 등 `?v=` 캐시버전 증가 필수** —
  `scripts/hook_postedit.py` 훅이 자동 수행(훅 없는 환경에선 수동).
  **프리뷰 검증 전 로드된 스크립트 버전부터 확인**(구버전 캐시 오탐 방지).
- 지도↔대시보드 양방향 연동(onChange 콜백 등)은 재진입 가드를 넣어
  상호 재트리거 루프를 방지.
- **신고가(is_peak)·고점대비(drop_pct)·신고가비중·추천(reco) 판정은 모두
  비슷한 크기(±12%)로 비교**한다(2026-07-10 파이프라인 감사에서 발견·수정).
  전 평형 혼합 최고가를 쓰면 대형 평형 역대가가 소형 평형 신고가를 가려
  is_peak가 틀리고 알림이 누락된다. `aggregate._matched_peak`,
  `notify.is_new_peak`, `reco._area_matched` 참고 — 새 신고가/추천 로직을
  추가할 때도 같은 원칙 적용.
- **일괄 수집 루프(collect.run_daily/run_backfill, building.collect_buildings)는
  개별 항목 실패를 삼키고 계속 진행**해야 한다. 한 (구,월) 또는 한 단지의
  API 오류로 전체 배치가 죽거나(예외 미처리 시 나머지 구 전부 스킵),
  실패를 성공처럼 영구 기록(bldg_fetched_at 등)하면 안 된다 — 실패분은
  기록하지 않고 다음 실행에서 자동 재시도되게 한다(사고 이력).

### 향후 과제로 남긴 것 (2026-07-10 감사, 우선순위 낮아 이번엔 미수정)
- `sale_txn` UNIQUE 키가 (complex_id, deal_date, exclu_area, floor, amount_manwon)
  자연키라 같은 날·같은 단지·같은 평형·같은 층·같은 금액의 **서로 다른 두 건**이
  1건으로 병합될 수 있음(대단지 동시분양 등에서 이론상 가능) — 거래량 관련
  지표(vol_ratio, volume_x_3m)가 미세하게 과소산정될 수 있음. MOLIT API에
  안정적인 거래 고유ID가 없어 스키마 변경 없이는 해결 어려움.
- `reb_api._extract_rows`가 응답 구조 이상(STATBL_ID 오류·인증만료 등)과
  "정상인데 데이터 없음"을 구분 못 하고 조용히 빈 리스트 반환 — 로그 추가하면
  운영 중 감지 가능.
- `molit_api.py`의 `deposit_manwon`/`monthly_manwon` 파싱은 `_to_int(...) or 0`
  이라 파싱 실패(None)와 진짜 0을 구분 못 함 — 실제 API가 숫자 필드라 위험은
  낮으나, 방어적으로 나누면 더 안전.
