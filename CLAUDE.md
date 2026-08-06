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

## 왼쪽 팝업 패널 레이아웃 (2026-07-23 분할→오버레이 전환)
- 대시보드·매수후보·비용계산·청약·**필터**가 **하나의 왼쪽 팝업 슬롯**을 공유한다
  (`app.js LEFT_PANELS`, `togglePanel`). 하나만 열리며, 열려 있는 걸 다시 누르면 닫힘.
- 예전엔 대시보드류가 지도를 오른쪽으로 **밀고**(`body.dash-open #map{left:…}`) 필터는
  오른쪽에서 밀어 지도가 양쪽에서 좁아졌다. 지금은 **지도는 그대로 두고 위에 겹쳐 뜬다** —
  단지 상세 패널과 같은 모양(`left:12px; top:62px; bottom:12px; border-radius:16px`,
  `--dash-w` 너비, 드래그 리사이즈). `.filter-panel` 은 `.dash-panel` 클래스를 함께 달아
  같은 배치를 쓰고 padding 만 따로 준다(`--filter-w`·`body.filter-open` 은 폐기).
- 지도 크기가 변하지 않으므로 **`map.relayout()` 호출은 제거**했다(예전엔 분할 때문에 필요).
- ⚠ 겹쳐 뜨는 구조라 **`centerAvoidingPanel` 이 상세 패널뿐 아니라 열린 왼쪽 팝업까지**
  가려진 폭으로 계산해야 한다. 왼쪽 가장자리부터 24px 이내로 이어진 세로 스트립들을
  한 덩어리로 보고 그 오른쪽 끝 너머로 센터를 민다(팝업+상세가 12px 간격으로 나란히 뜸).
  안 그러면 포커스한 단지가 팝업 밑에 숨는다(분할 시절엔 지도가 밀려 안 겪던 문제).

## 실구매 비용 계산기 (🧮 비용계산 탭, 2026-07-17 별도탭화)
- 상단바 `#btn-cost` → `#cost-panel`(왼쪽 팝업 슬롯 공유, `togglePanel`).
  지도 가격 푯말을 **드래그**(`cmp:` prefix 재사용)하거나
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

## 🏆 종합점수 패널 (2026-07-30 신설)
- 상단바 `#btn-score` → `#score-panel`(왼쪽 팝업 슬롯 공유). **전부 프런트 계산**
  (`dashboard.js` 6절: `SC_PRESETS`/`SC_PTS`/`scoreComplex`/`renderScore`) —
  markers + valuation + listings 를 결합하므로 백엔드 변경 없음.
- **4축**: 입지(지하철60·초등40) / 단지(세대수55·연차45 + ♻재건축 보너스 +20:
  연차30+·용적률<160%) / 가격(프리셋별) / 유동성(회전율70·매물30).
  지표별 **절대 구간표 + 선형 보간**(`SC_PTS`, `scInterp`) → 축 가중합 → 총점.
  등급 S85/A75/B60/C45/D.
- **프리셋 3종**(축 가중): 실거주 35/25/25/15 · 투자 25/15/35/25 · 갭투자 20/15/40/25.
  가격 축 내부: 실거주·투자 = pos40·jr30·drop15·prem15 / **갭투자 = 갭금액45·jr20·
  pos20·prem15**(같은 평형 매매-전세 절대 갭이 주 지표 - 억 단위 구간표).
- **결측 원칙**: 감점이 아니라 제외·재가중. 단 지하철/초등 null 은 상한(2km/1.5km)
  밖 '확정'이라 결측이 아닌 최저점. **축 2개 이하 단지는 순위 제외**(안 그러면
  가격·유동성 데이터 없는 나홀로 신축이 2축 만점으로 1~3위를 오염 - 실측 확인).
- 가격 축은 **선택 평형 기준**(대원칙), 특정 평형 선택 시 그 평형 매매 보유 단지만.
  구 시장국면은 점수 미반영·배지만(사용자 확정). 상태 `localStorage seoul_apt_score_v1`.
- 검증 기준: 1위 단지 수계산 대조(에스케이북한산시티 90.1 = 엔진 90 일치 확인).
  구간표를 바꾸면 같은 방식으로 수계산 재검증할 것.
- **입지 퀄리티 보강(2026-08-05)**: 거리만 보던 입지 축을 4지표로 재설계 —
  지하철(거리×노선계수: 2노선 ×1.05, 3+ ×1.10) 35 / **직주근접**(강남역·시청·여의도
  3대 CBD 최단 직선거리, 프런트 하버사인 `scCbdKm`) 25 / **학원가**(반경 1km 학원 수,
  카카오 AC5 — 실측 보정: 대치 1,689·목동 596·중계 338) 25 / 초등 15.
  검증: 은마(역 354m) 입지 95.9 vs 중계그린1(역 104m) 79.9 — 거리 조건이 더 좋아도
  직주근접(3.3 vs 11.6km)·학원가(1,157 vs 181)에서 갈림 = '강남 역세권 > 강북 역세권'.
- **퀄리티 데이터 수집(`poi` 명령 확장)**: `subway_lines`(KRIC CSV 재계산 — 역명
  정규화 `_station_key`: 괄호·'역' 제거로 운영사 표기차 흡수, 왕십리 2→4노선 교정.
  동명이역은 700m 거리 가드로 분리) + `academy_cnt`(카카오 카테고리 AC5 radius 1km,
  `meta.total_count` 1콜/단지, `academy_at` 증분·`--academy-limit`·`--no-academy`).
  markers 에 `swl`/`ac` export. ⚠진짜 '학군'(중학교 성취도)은 2017년 전수평가 폐지로
  공개 데이터가 없다 — 학원 밀집도가 프록시임을 UI에 명시.
- **가격 축 동급 상대화(2026-08-05, 사용자 지적)**: 가격 지표(pos·jr·drop)는 품질과
  역상관 — 입지가 나빠 싼 단지가 절대 구간표에서 가격 만점을 받아 종합점수를 끌어올렸다
  (autocorrelation). → **품질 Q(입지60·단지40)로 전체를 5분위**로 나누고 pos/jr/drop 을
  **같은 분위 안 midrank 백분위**로 점수화("이 급치고 싼가?"). `scBuildPeers`(경계·분포)
  + `scoreComplex(…, peers)`, renderScore 는 2패스(1패스=전체 서울 Q·원시값 수집 →
  2패스=상대화 채점). **예외 2개는 절대 유지**: prem(자기 실거래 대비 — 오염 없음)·
  gap(갭투자는 실제 묶이는 현금이 본질). 피어 통계는 **구 필터와 무관하게 전체 서울
  고정**(구를 좁혀도 채점 기준 불변), 표본 부족(전체<50·그룹지표<20)이면 절대 구간표 폴백.
  검증(2026-08-05): ①독립 재계산으로 1위 단지 가격 축 97.95 = 엔진 표시 98 일치
  ②분위별 가격 축 평균 41.7/40.5/41.1/44.3/50.1 → **47.4/48.3/47.8/48.8/49.1 로 균등화**
  (품질-가격 계통 상관 제거 확인) ③전체 top100 중 24개 교체. 재검증 시 브루트포스
  백분위(below+eq/2)/n 로 대조할 것.
- **정성 튜닝 3종(2026-08-07, 사용자 지적 "벽산라이브파크가 상위권")**:
  ①**경전철 할인** — 최인접역이 경전철(swn 에 우이신설|신림선|경량, 365단지)이면
  역세권 점수 ×0.75. 벽산라이브파크(우이신설 257m)가 지하철급 92점으로 Q5 에 올라
  "Q5치고 싸다"로 상위권이 되던 왜곡의 진범(가격 축이 아니라 입지 과대평가였다 —
  진단 없이 가격 축부터 만지지 말 것). 실거주 17위→57위.
  ②**가격 축 신뢰도 수축** — 결측 재가중만 하면 지표 1개(고점대비)만으로 98점
  (실측: 에비뉴나인티 1위). `price = 50 + (price−50)×√(사용가중/전체가중)`.
  ③**품질 연동 상한** — 총점 ≤ Q+15(💰상한 배지). 가격·유동성만으로는 S등급 불가
  (S 는 Q 70+ 필요). 검증: 오프라인 시뮬(scratchpad sc_tune.js 방식)과 엔진 표시
  전 지표 일치(벽산 loc 76.5/총점 81.0/순위 57 · top5 동일 · 콘솔 0).
  ⚠남은 관찰: 오피스텔·주상복합형 소형(스테이72여의도·메가스터디타워 등)이 구조적
  고전세가율·저갭으로 상위 잔존 — 유형 구분 데이터가 없어 미교정(추후 과제).
- ⚠**Release DB pull 시 로컬 전용 데이터 이식 필수**: listing 테이블(통째)·
  subway_lines/academy_cnt/academy_at·naver_no/zigbang_id 는 클라우드 DB에 없다.
  pull 전 백업 → ATTACH 로 이식(complex_id 는 두 DB가 같은 히스토리라 전수 일치 확인됨,
  이식 전 이름/구 대조 필수) → push 로 Release 에 반영해야 클라우드가 이어받는다.

## 청약·분양 UI (🏷️ 청약 패널, 2026-07-17 별도패널화)
- 상단바 `#btn-subs` = **청약 패널 열기**(왼쪽 팝업 슬롯 공유). 예전엔 이 버튼이 지도 마커 토글이었는데,
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
  **조회조건에도 같은 함정**: `RCRIT_PBLANC_DE::GTE` 는 서버측 문자열 비교라
  임의공급엔 `'20260715'`, 나머지엔 `'2026-07-15'` 를 넣어야 한다(`_api_date()`).
  섞으면 필터가 무시돼 전 기간이 딸려온다(149건 과다수신 확인 → 수정 후 정상).
- ⚠ **공공데이터 API는 청약홈 웹 캘린더보다 며칠 늦다**(2026-07-23 확인): 접수
  임박 공고가 API에 아직 없을 수 있다(7/27 해링턴플레이스 노원 센트럴 임의공급,
  7/28 아크로 리버스카이 무순위가 실제로 누락됐다). **누락처럼 보여도 대개 우리
  수집 버그가 아니라 원천 지연**이니, 의심되면 `ApplyhomeClient.fetch_notices` 로
  API에 실제로 있는지부터 확인할 것.

## 청약홈 웹 캘린더 보조수집 (`applyhome_web.py`, 2026-07-23)
- 위 지연을 메우려고 **API 기본 + 웹 캘린더 보조** 2단 구성. `collect_subscriptions`
  가 API 수집을 마친 뒤 `applyhome_web.supplement()` 로 **API에 아직 없는 공고만**
  추가한다(기존 공고는 손대지 않음 — 웹은 일정만 있어 덮으면 손해).
- 엔드포인트: `POST /ai/aib/selectSubscrptCalender.do`,
  본문 **`{"reqData": {"inqirePd": "202607"}}`** (reqData 로 감싸야 함),
  헤더 **`gvPgmId: AIB01M01`, `ajaxAt: Y`** 필수(없으면 `{"exception":"System Error"}`),
  사전에 캘린더 뷰 페이지 GET 으로 세션 쿠키(AH_JSESSION_ID) 확보. 이번 달+다음 달 조회.
- `RCEPT_SE` 매핑(화면 `houseSeClass`/`mbHouseSeClass` 기준): 01 특별·02 1순위·
  03 2순위 → `apt`, 06 → 무순위, 07 → 불법행위 재공급, 11 → 임의공급.
  04(공공지원민간임대)·05(오피스텔등)·08~10(민간사전청약)은 API 범위 밖이라 제외.
- 한 공고가 특별→1순위→2순위로 여러 날에 흩어져 오므로 **HOUSE_MANAGE_NO 로 묶어
  min/max 날짜를 접수 시작·종료**로 삼는다(월계 중흥: 7/27~7/30).
- 캘린더는 **일정만** 준다 — 주소·세대수·분양가·안전마진 없음. 그래서 `subscription.src`
  가 `'web'`이고 목록에 **`캘린더` 배지**(`.sub-prov`)를 붙여 "상세는 API 반영 후
  채워짐"을 알린다. 좌표는 주택명 키워드 지오코딩으로만 잡으므로
  `subscriptions_without_coords` 가 주소 없는 행도 반환한다. API가 따라잡으면
  `upsert_subscription` 이 정식 데이터로 덮고 `src='api'` 로 승격된다.
- 보조 소스라 **실패해도 API 수집분은 살린다**(try/except 로 감싸 경고만 출력).
  (청약 범위 자체는 **진행중·예정 + 최근 1년 마감분**을 유지 — 마감분은 경쟁률
  참고용이라 지우면 경쟁률 표가 성립하지 않는다.)
- **청약 목록·경쟁률 = 클릭 시 지도 이동**(`bindSubRows`, focusLatLng — 카드/행
  구분 없이 `[data-lat]` 로 바인딩) + **↗ 청약홈 링크**(각 공고 `url` =
  applyhome.co.kr 상세, 클릭과 분리된 `a` 태그).
  ⚠ kakao CustomOverlay 는 뷰포트 근처에서만 DOM 에 붙어 프리뷰 초기엔 `.sub-bubble`
  개수가 0으로 보일 수 있음 — 해당 위치로 focus 후 재확인.
- ⚠ **진행중·예정 목록은 표가 아니라 카드**(`.sub-card`, 2026-07-23 전환): 이 패널은
  폭이 460px(모바일 291px)이라 예전 9열 표에서 **주택명 칸이 33px 로 눌려 한 글자씩
  세로로 쪼개졌다**(행높이 245~294px). 열을 늘리지 말고 줄(`.sc-top`/`.sc-meta`)로
  쌓을 것. 한글은 글자 단위로 끊기므로 `word-break: keep-all` 필수(표 `.rank-table`
  에도 적용), 날짜는 `white-space: nowrap` 로 중간 분리 방지. 접수기간은
  `subPeriod()` 가 축약(같은 날이면 하루만, 같은 해면 종료일 연도 생략).

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

## 🔒 export 안전 가드 (2026-07-30 판매 전 감사에서 신설)

**로컬과 클라우드가 서로의 데이터를 덮어쓰는 사고가 실제로 났다** — 로컬에서 수집한
매물 2,858건을 다음날 클라우드 daily export 가 206건으로 덮음(93% 소실). 구조상
클라우드(Actions)는 Release DB로 실거래를 수집하고, **매물은 네이버 차단 위험 때문에
로컬에서만** 수집하기 때문. 양방향 클로버링을 export 에서 막는다.

- **낡은 DB 가드**(`export._guard_stale_db`): DB의 최신 계약일 < 배포된 meta.json 의
  실거래 기준일이면 **export 를 중단**. 로컬 DB가 며칠 낡은 채 export 해서 최근
  실거래가 통째로 빠진 구버전이 배포되는 걸 막는다. 강행은 `export --allow-stale`.
  → 로컬 작업 전에는 `scripts/db_release.sh pull` 또는 `collect` 를 먼저.
- **매물 보존 가드**: DB에 open 매물이 0건이면(=클라우드) `listings.json` 을 **새로
  쓰지 않고 배포본 그대로 보존**. 마커의 매물 배지(`ls`/`lj`)도
  `_published_listing_summary()` 가 배포된 markers.json 에서 승계한다.
  ⚠ 새 파일을 추가할 때 "로컬에서만 만들어지는 산출물"이면 같은 보존 규칙을 적용할 것.

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
