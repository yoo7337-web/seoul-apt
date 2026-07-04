# 서울 아파트 시세 지도 (seoul_apt)

서울 25개 자치구 아파트의 **매매/전세/월세 실거래가**, **공시가격**, **한국부동산원 시세지수**를
매일 수집·누적해 **카카오지도 기반 정적 사이트**(`docs/`)로 보여준다.
GitHub Actions(매일 09:00 KST)가 데이터를 갱신하고 GitHub Pages가 호스팅한다.

## 구성
```
seoul_apt/       수집·집계·내보내기 (Python)
  config.py      25개 구 코드·상수·면적버킷
  db.py          SQLite 스키마 + 멱등 upsert
  molit_api.py   국토부 실거래가 API(매매/전월세)
  geocode.py     카카오 지오코딩(주소→좌표) + 캐시
  reb_api.py     한국부동산원 R-ONE 지수
  gongsi.py      공시가격 대량 파일 파서
  collect.py     일일 증분 + 재개가능 백필
  aggregate.py   평단가·전세가율·거래량·랭킹 집계
  export.py      docs/data JSON 내보내기
  cli.py         명령행 진입점
data/seoul_apt.sqlite   누적 원천 DB(커밋됨)
docs/                    카카오지도 정적 사이트(GitHub Pages)
```

## 필요한 키 (환경변수)
`.env`(로컬, gitignore됨) 또는 GitHub Secrets 에 등록. 코드는 절대 하드코딩하지 않는다.

| 환경변수 | 용도 | 발급처 |
|---|---|---|
| `DATA_GO_KR_KEY` | 실거래가(매매·전월세) | data.go.kr (15126469 / 15126474 활용신청, Decoding 키) |
| `REB_API_KEY` | 부동산원 시세지수 | reb.or.kr R-ONE OpenAPI |
| `KAKAO_REST_KEY` | 지오코딩 | developers.kakao.com → REST API 키 |
| `KAKAO_JS_KEY` | 지도 표시 | developers.kakao.com → JavaScript 키 (플랫폼에 Pages 도메인 등록) |

> 공시가격은 별도 키 없이 data.go.kr 등에서 내려받은 대량 파일(CSV/XLSX)을
> `data/gongsi/` 에 두면 `gongsi` 명령이 적재한다.

## 사용법
```bash
pip install -r seoul_apt/requirements.txt

python -m seoul_apt.cli backfill            # 최근 5년 최초 수집(재개 가능)
python -m seoul_apt.cli collect             # 일일 증분(최근 3개월 재수집)
python -m seoul_apt.cli geocode             # 좌표 없는 신규 단지 지오코딩
python -m seoul_apt.cli gongsi              # data/gongsi 공시가격 적재
python -m seoul_apt.cli reb                 # 부동산원 지수 수집
python -m seoul_apt.cli export              # docs/data JSON 생성
python -m seoul_apt.cli all                 # collect+geocode+gongsi+reb+export
```

로컬 미리보기:
```bash
python -m seoul_apt.cli export
python -m http.server -d docs 8000    # http://localhost:8000
```

테스트:
```bash
python -m pytest seoul_apt/tests/ -q
```

## GitHub 설정 (최초 1회, 사용자 작업)
1. **Settings → Secrets and variables → Actions**: 위 4개 키 등록
2. **Settings → Pages**: Deploy from branch → `/docs`
3. **Settings → Actions → General**: Workflow permissions = **Read and write**
4. 카카오 개발자 콘솔 → 앱 → 플랫폼(Web)에 `https://<id>.github.io` 등록
5. 최초 백필: Actions 탭 → *Seoul Apt Daily Update* → *Run workflow* → mode=`backfill`

## 데이터 출처
- 국토교통부 아파트 매매/전월세 실거래가 (공공데이터포털)
- 공동주택 공시가격 (공공데이터포털 대량 파일)
- 한국부동산원 R-ONE 부동산통계 (전국주택가격동향조사 등)
