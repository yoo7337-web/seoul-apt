"""CLI 진입점.

  python -m seoul_apt.cli collect              # 일일 증분(최근 N개월)
  python -m seoul_apt.cli backfill [--from YYYYMM] [--to YYYYMM] [--force]
  python -m seoul_apt.cli geocode              # 좌표 없는 단지 지오코딩
  python -m seoul_apt.cli gongsi               # data/gongsi 파일 적재
  python -m seoul_apt.cli reb [--from] [--to]  # 부동산원 지수 수집
  python -m seoul_apt.cli export               # docs/data JSON 생성
  python -m seoul_apt.cli alerts [--dry-run]   # 관심지역 알림+다이제스트 발송
  python -m seoul_apt.cli reco                 # AI 추천용 후보 선별
  python -m seoul_apt.cli all                  # collect+geocode+gongsi+reb+export
"""

import argparse
import sys

from dotenv import load_dotenv

from . import (config, db, collect, export, geocode, gongsi, notify, reb_api,
               building, subscription)


def _kst_now_ym() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m")


def cmd_collect(conn, args):
    key = config.get_key(config.ENV_DATA_GO_KR)
    stats = collect.run_daily(conn, key, lookback=args.months)
    print(f"[collect] 매매 {stats['sale']} / 전월세 {stats['rent']} "
          f"(월: {', '.join(stats['months'])})")
    if stats["failed"]:
        print(f"[collect] 실패(다음 실행에 자동 재시도) {len(stats['failed'])}건: "
              f"{', '.join(stats['failed'])}")


def cmd_backfill(conn, args):
    key = config.get_key(config.ENV_DATA_GO_KR)
    stats = collect.run_backfill(conn, key, args.from_ym, args.to_ym, args.force)
    print(f"[backfill] 매매 {stats['sale']} / 전월세 {stats['rent']} "
          f"/ 건너뜀 {stats['skipped']} ({stats['start']}~{stats['end']})")
    if stats["failed"]:
        print(f"[backfill] 실패(다음 실행에 자동 재시도) {len(stats['failed'])}건: "
              f"{', '.join(stats['failed'][:10])}"
              f"{' ...' if len(stats['failed']) > 10 else ''}")


def cmd_geocode(conn, args):
    key = config.get_key(config.ENV_KAKAO_REST, required=False)
    if not key:
        print("[geocode] KAKAO_REST_KEY 없음 - 건너뜀")
        return
    n = geocode.geocode_missing(conn, key, args.district, args.limit)
    print(f"[geocode] {n}개 단지 좌표 갱신")


def cmd_gongsi(conn, args):
    n = gongsi.load_gongsi_files(conn)
    print(f"[gongsi] 공시가격 {n}건 적재 (파일 위치: {config.GONGSI_DIR})")


def cmd_building(conn, args):
    data_key = config.get_key(config.ENV_DATA_GO_KR)
    kakao_key = config.get_key(config.ENV_KAKAO_REST, required=False)
    if not kakao_key:
        print("[building] KAKAO_REST_KEY 없음 - 건너뜀(주소→법정동 변환 불가)")
        return
    stats = building.collect_buildings(conn, data_key, kakao_key,
                                       args.district, args.limit,
                                       max_workers=getattr(args, "workers", 10))
    print(f"[building] 조회 {stats['tried']} / 정보확보 {stats['filled']} "
          f"/ 실패(재시도예정) {stats['failed']}")


def cmd_subscription(conn, args):
    data_key = config.get_key(config.ENV_DATA_GO_KR)
    kakao_key = config.get_key(config.ENV_KAKAO_REST, required=False)
    stats = subscription.collect_subscriptions(
        conn, data_key, kakao_key,
        since=getattr(args, "since", None),
        debug=getattr(args, "debug", False))
    print(f"[subscription] APT {stats['apt']} / 무순위·불법행위재공급 {stats['remndr']} "
          f"/ 임의공급 {stats.get('optn', 0)} / 주택형 {stats['models']} "
          f"/ 경쟁률 {stats['cmpet']} / 웹캘린더 보조 {stats.get('web', 0)} "
          f"/ 지오코딩 {stats['geocoded']}")


def cmd_reb(conn, args):
    key = config.get_key(config.ENV_REB, required=False)
    if not key:
        print("[reb] REB_API_KEY 없음 - 건너뜀")
        return
    start = args.from_ym or config.BACKFILL_START_YM
    end = args.to_ym or _kst_now_ym()
    # --from 을 직접 준 경우엔 증분 시작점(DB 최신 기준)을 무시하고 그 시점부터 재수집
    n = reb_api.collect_reb(conn, key, start, end, force_start=bool(args.from_ym))
    print(f"[reb] 부동산원 지수 {n}건 적재")


def cmd_export(conn, args):
    js_key = config.get_key(config.ENV_KAKAO_JS, required=False)
    stats = export.export_all(conn, js_key,
                              allow_stale=getattr(args, "allow_stale", False))
    print(f"[export] 마커 {stats['markers']} / 매매 {stats['sale']} "
          f"/ 전월세 {stats['rent']} / 단지 {stats['complex']}")


def cmd_alerts(conn, args):
    notify.run_alerts(conn, dry_run=args.dry_run)


def cmd_reco(conn, args):
    from . import reco
    n = reco.build_candidates(conn)
    print(f"[reco] 후보 {n}건 → {config.RECO_PATH}")


def cmd_aireco(conn, args):
    from . import ai_reco, reco
    n = reco.build_candidates(conn)
    print(f"[reco] 후보 {n}건")
    text = ai_reco.weekly_recommendation()
    if not text:
        return
    if args.dry_run:
        print("[aireco] --dry-run 미리보기 ↓")
        print(text)
        return
    token = config.get_key(config.ENV_TG_TOKEN, required=False)
    chat = config.get_key(config.ENV_TG_CHAT, required=False)
    if token and chat:
        notify.send_telegram("🤖 <b>주간 AI 물건 추천</b>\n\n" + text, token, chat)
        print("[aireco] 텔레그램 발송 완료")
    else:
        print(text)


def _lawd_cd(v: str | None) -> str | None:
    """'광진구' 또는 '11215' → lawd_cd. 못 찾으면 예외."""
    if not v:
        return None
    if v in config.SEOUL_DISTRICTS:
        return v
    for cd, name in config.SEOUL_DISTRICTS.items():
        if name == v or name.rstrip("구") == v.rstrip("구"):
            return cd
    raise RuntimeError(f"'{v}' 는 서울 자치구가 아닙니다. 예: 광진구 또는 11215")


def cmd_listings(conn, args):
    from . import listings
    lawd = _lawd_cd(args.district)
    if lawd:
        print(f"[listings] 대상 구: {config.SEOUL_DISTRICTS[lawd]}"
              + ("" if args.active_only else " (거래 없는 단지 포함)"))
    stats = listings.collect(conn, scope=args.scope, source=args.source,
                             limit=args.limit, resume=not args.restart,
                             district=lawd, active_only=args.active_only)
    print(f"[listings] 단지 {stats['complexes']} / 매물 {stats['listings']} "
          f"(네이버 {stats['naver']} · 직방 {stats['zigbang']})"
          + (" · ⚠차단으로 중단(다음 실행 재개)" if stats.get("blocked") else ""))


def cmd_poi(conn, args):
    from . import poi
    kakao_key = None
    if not getattr(args, "no_academy", False):
        kakao_key = config.get_key(config.ENV_KAKAO_REST, required=False)
    out = poi.run(conn, refresh=args.refresh, kakao_key=kakao_key,
                  academy_limit=getattr(args, "academy_limit", None))
    ld = out["loaded"]
    nr = out["nearest"]
    print(f"[poi] 적재 지하철 {ld['subway']} / 초등 {ld['elem']}")
    if nr.get("no_poi"):
        print("[poi] poi 테이블 비어있음 — data/poi/*.csv 확인")
    else:
        print(f"[poi] 최근접 계산 단지 {nr['updated']}건 "
              f"(역 {nr.get('subways', 0)} · 학교 {nr.get('elems', 0)})")
    ac = out.get("academy")
    if ac:
        print(f"[poi] 학원 밀집도 {ac['academies']}건 수집 "
              f"(실패 {ac['failed']} · 남은 {ac['remaining']})")


def cmd_all(conn, args):
    cmd_collect(conn, args)
    cmd_geocode(conn, args)
    cmd_building(conn, args)
    cmd_gongsi(conn, args)
    cmd_reb(conn, args)
    try:
        cmd_subscription(conn, args)
    except Exception as e:          # 청약은 부가 기능 - 실패해도 export 진행
        print(f"[subscription] 실패(계속 진행): {e}")
    cmd_export(conn, args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="seoul_apt", description="서울 아파트 가격 추적기")
    p.add_argument("--db", default=str(config.DB_PATH), help="SQLite 경로")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="일일 증분 수집")
    c.add_argument("--months", type=int, default=None, help="재수집 개월 수")
    c.set_defaults(func=cmd_collect)

    b = sub.add_parser("backfill", help="과거 수집(재개 가능)")
    b.add_argument("--from", dest="from_ym", default=None, help="시작 YYYYMM")
    b.add_argument("--to", dest="to_ym", default=None, help="끝 YYYYMM")
    b.add_argument("--force", action="store_true", help="fetch_log 무시 재수집")
    b.set_defaults(func=cmd_backfill)

    g = sub.add_parser("geocode", help="좌표 없는 단지 지오코딩")
    g.add_argument("--district", default=None, help="특정 구 LAWD_CD")
    g.add_argument("--limit", type=int, default=None, help="처리 개수 제한")
    g.set_defaults(func=cmd_geocode)

    gs = sub.add_parser("gongsi", help="공시가격 파일 적재")
    gs.set_defaults(func=cmd_gongsi)

    bd = sub.add_parser("building", help="건축물대장 부가정보(세대수·용적률·건폐율)")
    bd.add_argument("--district", default=None, help="특정 구 LAWD_CD")
    bd.add_argument("--limit", type=int, default=None, help="처리 개수 제한")
    bd.add_argument("--workers", type=int, default=10,
                    help="동시 조회 스레드 수(기본 10 - 단지별 조회는 서로 독립적)")
    bd.set_defaults(func=cmd_building)

    sb = sub.add_parser("subscription", help="청약홈 분양정보·경쟁률 수집")
    sb.add_argument("--since", default=None, help="모집공고일 시작 YYYY-MM-DD")
    sb.add_argument("--debug", action="store_true",
                    help="첫 응답의 필드명 목록 출력(API 필드 확인용)")
    sb.set_defaults(func=cmd_subscription)

    r = sub.add_parser("reb", help="부동산원 지수 수집")
    r.add_argument("--from", dest="from_ym", default=None)
    r.add_argument("--to", dest="to_ym", default=None)
    r.set_defaults(func=cmd_reb)

    e = sub.add_parser("export", help="docs/data JSON 생성")
    e.add_argument("--allow-stale", action="store_true",
                   help="DB가 배포본보다 낡아도 강행(기본은 사고 방지를 위해 중단)")
    e.set_defaults(func=cmd_export)

    al = sub.add_parser("alerts", help="관심지역 알림+다이제스트 발송")
    al.add_argument("--dry-run", action="store_true",
                    help="발송 없이 메시지 미리보기(상태 미갱신)")
    al.set_defaults(func=cmd_alerts)

    rc = sub.add_parser("reco", help="AI 추천용 후보 선별(JSON 생성)")
    rc.set_defaults(func=cmd_reco)

    ar = sub.add_parser("aireco", help="Gemini 주간 추천 생성+발송")
    ar.add_argument("--dry-run", action="store_true",
                    help="발송 없이 추천 텍스트 미리보기")
    ar.set_defaults(func=cmd_aireco)

    po = sub.add_parser("poi", help="입지 레이어(역세권·초품아·학원) POI 적재+계산")
    po.add_argument("--refresh", action="store_true",
                    help="이미 계산된 단지도 다시 계산(기본은 미계산분만)")
    po.add_argument("--no-academy", action="store_true",
                    help="학원 밀집도 수집(카카오 API 호출) 건너뛰기")
    po.add_argument("--academy-limit", type=int, default=None,
                    help="학원 수집 단지 수 제한(테스트용)")
    po.set_defaults(func=cmd_poi)

    ls = sub.add_parser("listings", help="현재 매물(호가) 수집 - 네이버부동산+직방")
    ls.add_argument("--scope", choices=["watch", "seoul"], default="watch",
                    help="watch=거래활발 단지(기본), seoul=전역 스윕")
    ls.add_argument("--district", default=None,
                    help="자치구 한정(예: 광진구 또는 11215)")
    ls.add_argument("--all-complexes", dest="active_only", action="store_false",
                    help="거래 없는 단지까지 포함(기본은 최근1년 매매 3건+만)")
    ls.add_argument("--source", choices=["auto", "naver", "zigbang"], default="auto",
                    help="auto=네이버 우선+직방폴백(기본)")
    ls.add_argument("--limit", type=int, default=None, help="처리 단지 수 제한")
    ls.add_argument("--restart", action="store_true",
                    help="진행상태 무시하고 처음부터(기본은 중단분 이어하기)")
    ls.set_defaults(func=cmd_listings)

    a = sub.add_parser("all", help="collect+geocode+gongsi+reb+export")
    a.add_argument("--months", type=int, default=None)
    a.add_argument("--district", default=None)
    a.add_argument("--limit", type=int, default=None)
    a.add_argument("--from", dest="from_ym", default=None)
    a.add_argument("--to", dest="to_ym", default=None)
    a.set_defaults(func=cmd_all)
    return p


def main(argv=None):
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    try:
        args.func(conn, args)
    except RuntimeError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
