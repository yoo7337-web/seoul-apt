"""CLI 진입점.

  python -m seoul_apt.cli collect              # 일일 증분(최근 N개월)
  python -m seoul_apt.cli backfill [--from YYYYMM] [--to YYYYMM] [--force]
  python -m seoul_apt.cli geocode              # 좌표 없는 단지 지오코딩
  python -m seoul_apt.cli gongsi               # data/gongsi 파일 적재
  python -m seoul_apt.cli reb [--from] [--to]  # 부동산원 지수 수집
  python -m seoul_apt.cli export               # docs/data JSON 생성
  python -m seoul_apt.cli all                  # collect+geocode+gongsi+reb+export
"""

import argparse
import sys

from dotenv import load_dotenv

from . import config, db, collect, export, geocode, gongsi, reb_api


def _kst_now_ym() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m")


def cmd_collect(conn, args):
    key = config.get_key(config.ENV_DATA_GO_KR)
    stats = collect.run_daily(conn, key, lookback=args.months)
    print(f"[collect] 매매 {stats['sale']} / 전월세 {stats['rent']} "
          f"(월: {', '.join(stats['months'])})")


def cmd_backfill(conn, args):
    key = config.get_key(config.ENV_DATA_GO_KR)
    stats = collect.run_backfill(conn, key, args.from_ym, args.to_ym, args.force)
    print(f"[backfill] 매매 {stats['sale']} / 전월세 {stats['rent']} "
          f"/ 건너뜀 {stats['skipped']} ({stats['start']}~{stats['end']})")


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


def cmd_all(conn, args):
    cmd_collect(conn, args)
    cmd_geocode(conn, args)
    cmd_gongsi(conn, args)
    cmd_reb(conn, args)
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

    r = sub.add_parser("reb", help="부동산원 지수 수집")
    r.add_argument("--from", dest="from_ym", default=None)
    r.add_argument("--to", dest="to_ym", default=None)
    r.set_defaults(func=cmd_reb)

    e = sub.add_parser("export", help="docs/data JSON 생성")
    e.set_defaults(func=cmd_export)

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
