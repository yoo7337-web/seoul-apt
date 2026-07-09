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
                                       args.district, args.limit)
    print(f"[building] 조회 {stats['tried']} / 정보확보 {stats['filled']} "
          f"/ 실패(재시도예정) {stats['failed']}")


def cmd_subscription(conn, args):
    data_key = config.get_key(config.ENV_DATA_GO_KR)
    kakao_key = config.get_key(config.ENV_KAKAO_REST, required=False)
    stats = subscription.collect_subscriptions(
        conn, data_key, kakao_key,
        since=getattr(args, "since", None),
        debug=getattr(args, "debug", False))
    print(f"[subscription] APT {stats['apt']} / 무순위 {stats['remndr']} "
          f"/ 주택형 {stats['models']} / 경쟁률 {stats['cmpet']} "
          f"/ 지오코딩 {stats['geocoded']}")


def cmd_reb(conn, args):
    key = config.get_key(config.ENV_REB, required=False)
    if not key:
        print("[reb] REB_API_KEY 없음 - 건너뜀")
        return
    start = args.from_ym or config.BACKFILL_START_YM
    end = args.to_ym or _kst_now_ym()
    n = reb_api.collect_reb(conn, key, start, end)
    print(f"[reb] 부동산원 지수 {n}건 적재")


def cmd_export(conn, args):
    js_key = config.get_key(config.ENV_KAKAO_JS, required=False)
    stats = export.export_all(conn, js_key)
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
