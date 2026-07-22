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
- 관심단지 텔레그램 알림: 지도에서 ★ 등록 → [★ 관심 → 📋 알림설정 복사] →
  `config/watchlist.yml`의 `complexes:`에 붙여넣기(정적 사이트라 이 1회 수동
  연결 필요). 등록된 단지 거래는 다이제스트 최상단 ⭐섹션에 표시.

### 외부 배포 (GitHub Pages + 구글 로그인, 2026-07-14 구축)
- URL: **https://yoo7337-web.github.io/seoul-apt/** (repo `yoo7337-web/seoul-apt`, main/`docs`)
- **전제조건: repo가 Public이어야 함** — 무료 플랜은 Private repo에서 GitHub Pages 미지원
  (`422 Your current plan does not support GitHub Pages for this repository`). Private→Public
  전환은 접근권한 변경이라 사용자가 직접 GitHub 웹(Settings > Danger Zone)에서 수행.
- Pages 활성화는 repo가 Public이 된 뒤 `gh api -X POST repos/yoo7337-web/seoul-apt/pages
  -f "source[branch]=main" -f "source[path]=/docs"` (또는 Settings > Pages 웹에서).
- 로그인: Firebase Auth(To-Do의 `career-board-fc111` 프로젝트 재사용, `docs/js/firebase-config.js`) —
  구글 signInWithPopup + **허용 이메일 화이트리스트**(`window.ALLOWED_EMAILS`, 현재 yoo7337@gmail.com만).
  게이트 로직은 `docs/js/auth.js`, index.html·dashboard.html·devlog.html 3곳 모두 head에 로드.
  **localhost는 게이트 자동 스킵**(로컬 개발·프리뷰 영향 없음). authDomain이 `yoo7337-web.github.io`라
  같은 계정의 다른 github.io 배포(career-board, chart-principles)와 승인 도메인을 공유 — 추가 설정 불필요.
- ⚠ 한계(chart-principles와 동일): **공개 repo + 정적 사이트라 로그인 게이트는 UI 차원**일 뿐,
  ① repo 자체(코드·`config/watchlist.yml`의 관심지역 등)는 github.com에서 로그인 없이 그대로 열람·clone
  가능, ② `docs/data/*.json`도 URL을 알면 로그인 없이 직접 fetch 가능(백엔드 없는 정적 사이트라 원천
  차단 불가). 실거래가 데이터 자체는 국토부 공개정보라 민감하지 않음 — 진짜 비공개가 필요해지면
  별도 백엔드 필요.
- **Pages가 라이브인 이상 `docs/js·css·html` 수정은 커밋만으로 안 끝난다 — 반드시 `git push`까지
  완료해야 실사이트에 반영된다**(main/docs를 그대로 서빙하므로 push=배포). 코드 수정 작업의 마지막
  단계로 항상 `git push`를 실행하고, 그냥 성공했다고 넘기지 말고:
  1. push가 non-fast-forward로 거부되면(Actions daily/weekly 자동커밋과 겹칠 수 있음) `git fetch` →
     `git rebase origin/main`(merge 말고 rebase로 히스토리 유지) → 재push.
  2. 배포 확인이 필요한 변경(사용자가 직접 확인 요청했거나 중요한 수정)은 push 후
     `gh api repos/yoo7337-web/seoul-apt/pages/builds/latest`로 `status:"built"`와
     `commit`이 방금 push한 SHA(`git rev-parse HEAD`)와 일치하는지 확인 — 지금 세션에서 이미
     확인된 패턴. 로그인 게이트 때문에 실사이트 브라우저 확인은 제한적이니(구글 로그인은 직접
     수행 불가) 빌드 상태 확인으로 대체.
  3. 로컬 프리뷰(8511, 게이트 스킵)에서 먼저 검증 후 push하는 기존 절차는 그대로 유지.

## 현재 매물(호가) 수집 (`listings` 명령, 2026-07-17 구축)

⭐ 트리거: **"매물 수집해줘"** → `.venv\Scripts\python.exe -m seoul_apt.cli listings`
(옵션: `--scope watch|seoul`, `--source auto|naver|zigbang`, `--limit N`, `--restart`)
수집 후 반드시 `export` 재실행해야 사이트에 반영된다.

- **네이버부동산이 주 소스**(커버리지·품질 압도적. 은마 매매 329건 vs 직방 1건).
  일반 requests 는 TLS 핑거프린팅으로 **무조건 429** → `curl_cffi`(Chrome
  impersonate)로 우회. 이건 우회가 아니라 **정상 브라우저 흉내**라 잘 동작하지만,
  네이버가 정책을 바꾸면 깨질 수 있다(그때는 직방 폴백 + 링크아웃이 안전망).
- **확인된 무인증 경로**(2026-07 검증):
  `new.land/api/search?keyword=단지명` → complexNo·좌표·cortarNo (단지 매칭용) /
  fin.land `front-api/v1/complex/buildingList`·`pyeongList`·
  `building/article/list`(complexNumber×buildingNumber×pyeongTypeNumber 순회).
  **new.land 의 complexNo 와 fin.land 의 complexNumber 는 같은 체계**(검증됨).
  `POST /complex/article/list` 는 스키마가 까다로워 400 — GET 3종 조합을 쓸 것.
  `articles` 는 층별 dict, 값은 리스트, **대표매물 기준으로 세야 실제 물건 수**
  (totalCount 는 중복 중개사 등록 포함이라 더 큼).
- **단지 매칭은 좌표가 주 신호**(±120m), 이름은 보조. 국토부↔네이버 표기차가 잦다
  ('인왕산아이파크'↔'인왕산현대아이파크', '효성쥬얼리시티'↔'효성주얼리시티').
  괄호 든 이름은 검색 0건이라 괄호 제거 후 재검색. **좌표 ≤50m 면 이름 달라도 채택**.
  '현대'·'롯데캐슬' 같은 일반명은 오매칭 위험이 커 매칭 실패로 두는 게 맞다
  (실패 단지는 프런트에서 네이버 **검색 링크아웃**으로 폴백).
- **차단 안전장치**: 요청 간격 1.2s+jitter / 429 시 지수 백오프(60→300s, 초과 시
  세션 중단) / 세션 요청 상한 / `data/listings_state.json` 진행상태 → 중단분 재개.
  **GitHub Actions(해외 IP)에는 넣지 말 것** — 차단 위험. 로컬 실행 전제.
- **호가 괴리(prem)** 는 대원칙대로 같은 크기(±12%)·최근 1년 실거래 중앙값 대비.
  표본<3이면 미표시. 매매만 계산(전세 실거래는 rent_txn 이라 비교 불가).
- 내려간 매물은 삭제하지 않고 `status='gone'`(이력 보존), 다시 올라오면 open 복구.
- **단지 상세 패널 평형 선택 연동**(2026-07-18): 패널 상단에 평형 선택기
  (`areaSelectTop`→`areaTabs`, `state.detailArea`, 여러 평형 단지만 표시). 선택 시
  가격카드·전세가율·차트·실거래에 더해 **현재 매물(`listingsHtml`)도 그 평형만**
  필터(매매/전세 탭 건수도 해당 평형 기준). 매물 필터는 export 가 각 매물에 넣는
  `b`(=`config.area_bucket(area_m2)`) 기준, 없으면 `py→㎡` 폴백. 선택기는 예전
  차트 앞 위치에서 상단으로 이동(중복 제거).

## 실구매 비용 계산기 (🧮 비용계산 탭, 2026-07-17 별도탭화)
- 상단바 `#btn-cost` → `#cost-panel`(대시보드·매수후보와 같은 왼쪽 슬롯 공유,
  `togglePanel` 3-way). 지도 가격 푯말을 **드래그**(`cmp:` prefix 재사용)하거나
  단지명 검색으로 여러 단지를 끌어와 필요현금을 나란히 비교. 매수가 셀은 편집 가능.
  상태는 `localStorage seoul_apt_cost`. 렌더는 `dashboard.js renderCost/renderCostBody`,
  계산은 `app.js calcCost`(SeoulMap.calcCost로 노출해 재사용). 상세 패널 내
  기존 접이식 계산기(costCalcHtml)는 제거됨.
- **평형대 선택**(2026-07-18): 단지마다 **평형대 드롭다운**(`.cost-bucket-sel`,
  마커 `sale_area`의 매매가 있는 버킷만, 평 병기). 선택 평형대의 최근매매가·
  전용면적으로 재계산 → 전용 85㎡ 초과 시 농특세 자동 반영, 대출 한도캡도
  그 가격 기준. 기본은 대표평형(rep). 평형 바꾸면 수기편집 매수가는 리셋(그
  평형 기본가로). `costBucket`(id→버킷) localStorage 저장. `costDefaults`가
  `costSelBucket`으로 선택 평형 해석. 이전엔 대표평형만 반영됐음(개선).
- **현행 규제 반영(2026-07)**: ⚠ 서울 전역이 규제지역이라 **주담대 한도 캡**이 핵심 —
  `calcCost`에서 `loanCap = eok<=15?6억 : eok<=25?4억 : 2억`(만원), `loan=min(가격×LTV,cap)`.
  이게 없으면 30억에 LTV 40%가 12억 대출로 잘못 나온다(실제 2억 캡). LTV 슬라이더 상한 40%.
  취득세는 서울 전역 조정지역이라 2주택 8%·3주택+ 12% 그대로. 토허구역 실거주 2년·
  DSR 스트레스금리 3% 등은 계산 아닌 **안내 카드**로만(개인 조건별 정밀 대출한도·
  생애최초 우대·보유세는 미반영, 참고용 명시).

## 매수 테마 프리셋 (⭐ 필터 패널 상단, 2026-07-18)
- 주식 스크리너 '테마'처럼 **필터 조합 원클릭 적용**: `app.js THEMES` 10종
  (낙폭과대 반등후보·최소갭 투자·전세방어 실수요·역세권 국평·초품아 패밀리·
  신축 대단지·재건축 잠재·가성비 구축 대단지·신고가 모멘텀·환금성 최상).
- 동작: 칩 클릭 = **필터 전체 초기화 후 그 조합만 적용**(누적 아님), 재클릭 =
  해제(초기화). 슬라이더/토글 **수동 조작 시 칩 강조만 해제**(`clearThemeMark`,
  필터 값은 유지 — 테마에서 출발해 미세조정하는 흐름 지원). `state.themeKey`.
- 테마는 하드코딩 프리셋, 💼 내 프로필(사용자 저장 스냅샷)과 별개 공존.
  새 테마 추가 시 THEMES 배열에 {key, icon, name, desc, range, peak?/minusGap?}만.

## 청약·분양 UI (🏷️ 청약 패널, 2026-07-17 별도패널화)
- 상단바 `#btn-subs` = **청약 패널 열기**(`togglePanel` 4-way, 대시보드·매수후보·
  비용계산과 같은 왼쪽 슬롯 공유). 예전엔 이 버튼이 지도 마커 토글이었는데,
  **지도 표시 여부는 패널 안 체크박스**(`#subs-map-toggle` → `setSubsMarkers`)가 담당.
  청약 목록·경쟁률 표는 대시보드에서 이 패널로 이동(`#subs-table-wrap`,
  `#subs-cmpet-wrap`, `dashboard.js renderSubs` + `SeoulDash.openSubs`).
- 마커 표시 상태는 `localStorage seoul_apt_show_subs`(0/1). 헤더 버튼은 마커가
  켜져 있으면 강조(active)되고 진행중·예정 건수 배지 유지. 청약 마커는
  `app.js renderSubMarkers`(`.sub-bubble` 커스텀 오버레이, subVisibleOnMap 필터).
- **마커 상태 시각 구분**(2026-07-18): 접수중=초록+펄스(지금 청약 가능 강조),
  예정=보라, 발표대기=주황, 완료=회색·투명도0.72·축소(subVisibleOnMap 이 완료를
  마감 90일까지만 노출). 패널에 색 범례(`.subs-legend`) 표시.
- ⚠ **청약홈 날짜 포맷이 오퍼레이션마다 다르다**(2026-07-23 발견·수정): APT·무순위는
  `2026-07-27`, **임의공급(getOPTLttotPblancDetail)은 `20260727`**. 상태 판정
  (`subStatus`)이 날짜 **문자열 비교**라, 섞이면 `'20260108' > '2026-07-23'`
  (`'0'`>`'-'`)이 되어 **지난 임의공급 공고가 전부 '예정'으로 오표시**된다(실제
  18건). 저장 전 반드시 `subscription._norm_date()` 를 거칠 것 — `_parse_notice`
  의 날짜 6종에 적용돼 있다. 기존 행은 `db._migrate()` 가 1회 정규화한다.
  (청약 범위 자체는 **진행중·예정 + 최근 1년 마감분**을 유지 — 마감분은 경쟁률
  참고용이라 지우면 경쟁률 표가 성립하지 않는다.)
- **청약 목록·경쟁률 표 = 행 클릭 시 지도 이동**(`bindSubRows`, focusLatLng) +
  **↗ 청약홈 링크**(각 공고 `url` = applyhome.co.kr 상세, 행클릭과 분리 `a` 태그).
  ⚠ kakao CustomOverlay 는 뷰포트 근처에서만 DOM 에 붙어 프리뷰 초기엔 `.sub-bubble`
  개수가 0으로 보일 수 있음 — 해당 위치로 focus 후 재확인.

## 입지 레이어(역세권·초품아, `poi` 명령)

- 데이터는 준불변이라 1회 적재 후 재계산만 하면 된다(daily Action 불필요).
  `data/poi/subway_stations.csv`(전국도시철도역사정보표준데이터·KRIC, 수도권 필터),
  `data/poi/schools_seoul.csv`(카카오 키워드검색으로 서울 25구 초등학교, 좌표 포함).
  두 CSV는 커밋되어 있으므로 `poi` 명령만 실행하면 재현된다.
- `.venv\Scripts\python.exe -m seoul_apt.cli poi` — CSV를 `poi` 테이블에 적재하고
  좌표 보유 단지의 최근접 지하철역·초등학교 직선거리(m)를 계산해
  `complex.subway_m/subway_nm/school_m`에 저장(미계산 단지만 증분, `--refresh`로 전체).
- 최근접 상한: 지하철 2km·초등 1.5km. 그 밖이면 NULL(역세권/초품아 아님)로
  지도 필터·패널에서 제외. 도보 환산은 약 67m/분.
- CSV 재생성 소스: KRIC 도시철도 XLSX는
  `https://data.kric.go.kr/rips/dataset/download.file?type=filedata&id=32&operation=1`
  (세션 쿠키 필요), 초등학교는 Kakao Local 키워드검색 `{구}+초등학교`(category SC4,
  place_name·category가 '초등학교'로 끝나고 주소가 '서울'로 시작하는 것만).
  ⚠ NEIS 학교API는 인증키 없이 5건만 반환하므로 사용 금지(사고 이력).

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
- **`focusComplex`로 지도를 재센터링할 때 좌측 상세 패널에 가려지는 문제**
  (2026-07-11 발견·수정): `map.setCenter()`는 지도 div의 '진짜 중앙'에
  타겟을 놓는데, 매수후보 리스트+상세 패널이 함께 열린 창 너비(1280px
  안팎, 흔한 랩탑 해상도)에서는 그 자리가 하필 열려 있는 `.panel` 밑이라
  방금 클릭한 단지 자신의 버블이 안 보인다. `app.js`의
  `centerAvoidingPanel()`이 패널이 지도 왼쪽에 붙은 세로 스트립일 때
  화면에 남는 폭 쪽으로 밀어서 센터링한다. **주의**: `openComplex()`는
  비동기(fetch)라 패널의 `.hidden` 클래스는 그게 끝나야 벗겨진다 —
  `centerAvoidingPanel`을 `openComplex` 완료 **후**에 호출해야 한다(먼저
  호출하면 항상 hidden으로 보여 보정이 스킵된다).
- **평형 버킷 맥락은 `focusComplex(id, areaHint)`로 명시 전달**해야 한다
  (2026-07-11 발견·수정): 매수후보 리스트가 "18~26평" 버킷 기준 값을
  보여줘도, 힌트 없이 열면 지도 버블·상세 패널은 단지의 대표평형(rep,
  다른 크기일 수 있음)을 기본으로 보여줘 리스트 값과 어긋난다(동양넥스빌:
  리스트는 26평 -49.6%인데 지도는 18평 6.3억을 보여준 사고). 특정 평형
  맥락에서 여는 곳(밸류에이션 리스트→버킷 키 문자열, 급매 리스트→실거래
  전용면적 ㎡ 숫자)은 반드시 `focusComplex`/`openComplex`에 `areaHint`를
  넘긴다. `markerInfo()`도 `state.selectedId`가 자기 자신이면
  `state.detailArea`를 우선해 버블과 패널이 같은 평형을 보여주게 한다.

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
