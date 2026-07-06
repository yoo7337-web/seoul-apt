"""관심지역 알림 + 일일 다이제스트 (텔레그램).

동작:
  1. notify_state.json 의 last_sale_id 이후 새로 적재된 매매 거래를 찾는다.
  2. 서울 전체 요약(다이제스트) + 워치리스트 매칭 알림(신규거래/신고가/급변동)을
     한 메시지로 조립해 텔레그램으로 보낸다.
  3. 성공 시 last_sale_id 를 갱신한다(dry-run 은 갱신하지 않음).

텔레그램 발송은 deal-radar 와 동일한 Bot API 직접 호출 패턴을 쓴다.
"""

import json
import time
from collections import defaultdict
from datetime import date, timedelta

import requests
import yaml

from . import config
from .aggregate import _median, _pyeong
from .subscription import extract_gu

BARGAIN_THRESHOLD = -7.0    # 동일평형 중앙값 대비 이만큼 낮으면 급매
BARGAIN_MIN_SAMPLE = 5      # 비교 기준 최근 표본 최소치
BARGAIN_LOW_FLOOR = 2       # 이 층 이하는 급매 판정 제외(저층 디스카운트)
BARGAIN_MIN_DISC = -40.0    # 이보다 큰 하락은 지분·증여성 등 비정상 거래로 보고 제외

TG_API = "https://api.telegram.org/bot{token}/sendMessage"
TG_MAX_LEN = 3900          # 텔레그램 4096 한도 여유분
SEND_INTERVAL = 1.5        # 메시지 간 간격(초)
MAX_RETRIES = 4


# ── 설정/상태 ────────────────────────────────────────────────────────────
def load_watchlist(path=None) -> dict:
    path = path or config.WATCHLIST_PATH
    if not path.exists():
        return {"watches": [], "swing_threshold_pct": 5,
                "swing_min_sample": 5, "digest_peak_limit": 5}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("watches", [])
    data.setdefault("swing_threshold_pct", 5)
    data.setdefault("swing_min_sample", 5)
    data.setdefault("digest_peak_limit", 5)
    return data


def load_state(path=None) -> dict:
    path = path or config.NOTIFY_STATE_PATH
    if not path.exists():
        return {"last_sale_id": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_sale_id": 0}


def save_state(state: dict, path=None) -> None:
    path = path or config.NOTIFY_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ── 감지 ────────────────────────────────────────────────────────────────
def new_sales(conn, since_id: int) -> list:
    """since_id 이후 적재된 매매 거래(해제 제외) + 단지 정보."""
    return conn.execute(
        """SELECT s.id, s.deal_date, s.exclu_area, s.floor, s.amount_manwon,
                  s.complex_id, c.lawd_cd, c.umd_nm, c.apt_nm
           FROM sale_txn s JOIN complex c ON s.complex_id=c.complex_id
           WHERE s.id > ? AND s.canceled=0
           ORDER BY s.id""", (since_id,)).fetchall()


def match_watch(row, watch: dict) -> bool:
    if row["lawd_cd"] != watch.get("lawd_cd"):
        return False
    umd = watch.get("umd") or []
    if umd and (row["umd_nm"] or "") not in umd:
        return False
    pat = (watch.get("apt_pattern") or "").strip()
    if pat and pat not in (row["apt_nm"] or ""):
        return False
    return True


def is_new_peak(conn, row) -> bool:
    """해당 거래가 그 단지의 역대 최고가(신고가)인지. 과거 거래가 없으면 False."""
    prev = conn.execute(
        """SELECT MAX(amount_manwon) AS m, COUNT(*) AS n FROM sale_txn
           WHERE complex_id=? AND canceled=0 AND id != ?""",
        (row["complex_id"], row["id"])).fetchone()
    if not prev["n"]:
        return False
    return row["amount_manwon"] > prev["m"]


def watch_swing(conn, watch: dict, threshold_pct: float,
                min_sample: int) -> dict | None:
    """관심지역 평단가 월 중앙값의 전월비 급변동 감지."""
    q = """SELECT s.deal_date, s.exclu_area, s.amount_manwon
           FROM sale_txn s JOIN complex c ON s.complex_id=c.complex_id
           WHERE s.canceled=0 AND c.lawd_cd=?"""
    args: list = [watch["lawd_cd"]]
    umd = watch.get("umd") or []
    if umd:
        q += f" AND c.umd_nm IN ({','.join('?' * len(umd))})"
        args += umd
    pat = (watch.get("apt_pattern") or "").strip()
    if pat:
        q += " AND c.apt_nm LIKE ?"
        args.append(f"%{pat}%")
    rows = conn.execute(q, args).fetchall()

    ppy_by_m = defaultdict(list)
    for r in rows:
        py = _pyeong(r["exclu_area"])
        if py > 0:
            ppy_by_m[r["deal_date"][:7]].append(r["amount_manwon"] / py)
    months = sorted(m for m, v in ppy_by_m.items() if len(v) >= min_sample)
    if len(months) < 2:
        return None
    cur_m, prev_m = months[-1], months[-2]
    cur = _median(ppy_by_m[cur_m])
    prev = _median(ppy_by_m[prev_m])
    if not (cur and prev):
        return None
    pct = (cur - prev) / prev * 100
    if abs(pct) < threshold_pct:
        return None
    return {"prev_month": prev_m, "cur_month": cur_m,
            "prev_ppy": round(prev), "cur_ppy": round(cur),
            "pct": round(pct, 1)}


BARGAIN_AREA_TOL = 0.12     # 비교 대상 전용면적 허용 오차(±12%)


def bargain_deals(conn, rows, threshold: float = BARGAIN_THRESHOLD) -> list[dict]:
    """신규 거래 중 '급매' - 동일 단지·비슷한 전용면적(±12%) 최근 1년 중앙값
    대비 threshold%(기본 -7%) 이하로 낮은 거래. 저층(≤2층)은 제외해 오탐을 줄인다.
    버킷(~60㎡ 등)은 폭이 넓어 소형이 대형과 섞이므로 면적 근접 비교를 쓴다.
    매수자에게 실질적으로 가장 유용한 반대(하락) 신호."""
    since = (date.today() - timedelta(days=365)).isoformat()
    out = []
    for r in rows:
        if r["floor"] and r["floor"] <= BARGAIN_LOW_FLOOR:
            continue
        area = r["exclu_area"]
        lo, hi = area * (1 - BARGAIN_AREA_TOL), area * (1 + BARGAIN_AREA_TOL)
        amts = [x["amount_manwon"] for x in conn.execute(
            "SELECT amount_manwon FROM sale_txn WHERE complex_id=? AND canceled=0 "
            "AND id!=? AND deal_date>=? AND exclu_area BETWEEN ? AND ?",
            (r["complex_id"], r["id"], since, lo, hi))]
        if len(amts) < BARGAIN_MIN_SAMPLE:
            continue
        med = _median(amts)
        if not med:
            continue
        disc = round((r["amount_manwon"] - med) / med * 100, 1)
        if disc <= threshold and disc >= BARGAIN_MIN_DISC:
            out.append({"row": r, "med": med, "disc": disc})
    out.sort(key=lambda x: x["disc"])   # 할인폭 큰 순
    return out


# ── 메시지 조립 ──────────────────────────────────────────────────────────
def _fmt_amount(manwon: int) -> str:
    if manwon >= 10000:
        v = manwon / 10000
        return f"{v:.1f}억".replace(".0억", "억")
    return f"{manwon:,}만"


def _district_name(lawd_cd: str) -> str:
    return config.SEOUL_DISTRICTS.get(lawd_cd, lawd_cd)


def build_message(conn, wl: dict, rows: list) -> str:
    """다이제스트 + 워치 알림 전체 메시지(HTML)."""
    lines: list[str] = []
    lines.append("🏙️ <b>서울 아파트 일일 다이제스트</b>")
    lines.append("")

    # ── 서울 전체 요약
    by_gu = defaultdict(int)
    for r in rows:
        by_gu[r["lawd_cd"]] += 1
    lines.append(f"신규 수집 거래: <b>{len(rows):,}건</b>")
    if by_gu:
        top3 = sorted(by_gu.items(), key=lambda x: -x[1])[:3]
        gu_txt = " · ".join(f"{_district_name(g)} {n}건" for g, n in top3)
        lines.append(f"구별 상위: {gu_txt}")

    # ── 신규 신고가(서울 전체, 금액 상위)
    peaks = [r for r in rows if is_new_peak(conn, r)]
    if peaks:
        peaks.sort(key=lambda r: -r["amount_manwon"])
        limit = wl.get("digest_peak_limit", 5)
        lines.append("")
        lines.append(f"📈 <b>신규 신고가</b> ({len(peaks)}건)")
        for r in peaks[:limit]:
            lines.append(
                f" · {_district_name(r['lawd_cd'])} {r['apt_nm']} "
                f"{r['exclu_area']}㎡ {_fmt_amount(r['amount_manwon'])} "
                f"({r['deal_date']})")
        if len(peaks) > limit:
            lines.append(f"   … 외 {len(peaks) - limit}건")

    # ── 급매 포착(동일평형 중앙값 대비 하락 거래)
    watch_lawds = {w["lawd_cd"] for w in wl.get("watches", []) if w.get("lawd_cd")}
    bargains = bargain_deals(conn, rows)
    if bargains:
        lines.append("")
        lines.append(f"🔻 <b>급매 포착</b> (동일평형 중앙값 대비 "
                     f"{int(BARGAIN_THRESHOLD)}%↓ · {len(bargains)}건)")
        for b in bargains[:10]:
            r = b["row"]
            star = "⭐ " if r["lawd_cd"] in watch_lawds else ""
            lines.append(
                f" · {star}{_district_name(r['lawd_cd'])} {r['apt_nm']} "
                f"{r['exclu_area']}㎡ {r['floor'] or '-'}층 "
                f"{_fmt_amount(r['amount_manwon'])} "
                f"(<b>{b['disc']}%</b> · 중앙값 {_fmt_amount(round(b['med']))})")
        if len(bargains) > 10:
            lines.append(f"   … 외 {len(bargains) - 10}건")

    # ── 워치리스트 섹션
    for watch in wl.get("watches", []):
        alerts = watch.get("alerts") or []
        matched = [r for r in rows if match_watch(r, watch)]
        section: list[str] = []

        if "new_deal" in alerts and matched:
            section.append(f"신규 실거래 {len(matched)}건")
            for r in matched[:10]:
                mark = " 🚩신고가" if r in peaks else ""
                section.append(
                    f" · {r['apt_nm']} {r['exclu_area']}㎡ {r['floor'] or '-'}층 "
                    f"{_fmt_amount(r['amount_manwon'])} ({r['deal_date']}){mark}")
            if len(matched) > 10:
                section.append(f"   … 외 {len(matched) - 10}건")
        elif "new_peak" in alerts:
            watch_peaks = [r for r in matched if r in peaks]
            for r in watch_peaks:
                section.append(
                    f" 🚩 신고가: {r['apt_nm']} {r['exclu_area']}㎡ "
                    f"{_fmt_amount(r['amount_manwon'])} ({r['deal_date']})")

        if "swing" in alerts:
            sw = watch_swing(conn, watch, wl["swing_threshold_pct"],
                             wl["swing_min_sample"])
            if sw:
                arrow = "▲" if sw["pct"] > 0 else "▼"
                section.append(
                    f" {arrow} 평단가 급변동: {sw['prev_month']} "
                    f"{sw['prev_ppy']:,} → {sw['cur_month']} {sw['cur_ppy']:,}"
                    f"만원/평 ({sw['pct']:+.1f}%)")

        if section:
            lines.append("")
            lines.append(f"⭐ <b>{watch.get('name', '관심지역')}</b>")
            lines.extend(section)

    return "\n".join(lines)


# ── 청약·분양 소식 ──────────────────────────────────────────────────────
def watch_gu_names(wl: dict) -> set[str]:
    """워치리스트의 구 이름 집합(청약 공고 주소 매칭용)."""
    return {config.SEOUL_DISTRICTS[w["lawd_cd"]]
            for w in wl.get("watches", [])
            if w.get("lawd_cd") in config.SEOUL_DISTRICTS}


def subscription_news(conn, known_ids: set, today: str,
                      watch_gus: set[str]) -> tuple[list[str], set]:
    """청약 소식 라인 + 이번에 새로 알게 된 공고 id 집합.

    ① 신규 모집공고(known_ids에 없는 것) ② 오늘 청약접수 시작.
    워치리스트 구의 공고는 ⭐ 강조. subscription 테이블이 비어 있으면 조용히 통과.
    """
    rows = conn.execute(
        """SELECT house_manage_no, kind, house_nm, adres, tot_suply,
                  rcept_bgnde, rcept_endde, url
           FROM subscription
           WHERE rcept_endde IS NULL OR rcept_endde >= ?
           ORDER BY rcept_bgnde""", (today,)).fetchall()
    lines: list[str] = []
    new_ids: set = set()

    def _line(r) -> str:
        gu = extract_gu(r["adres"]) or ""
        star = "⭐ " if gu in watch_gus else ""
        kind = " (무순위)" if r["kind"] == "remndr" else ""
        tot = f" {r['tot_suply']:,}세대" if r["tot_suply"] else ""
        period = ""
        if r["rcept_bgnde"]:
            period = f" · 접수 {r['rcept_bgnde']}~{r['rcept_endde'] or ''}"
        return f" · {star}{gu} {r['house_nm']}{kind}{tot}{period}"

    fresh = [r for r in rows if r["house_manage_no"] not in known_ids]
    if fresh:
        lines.append(f"🏷️ <b>신규 분양공고</b> ({len(fresh)}건)")
        lines.extend(_line(r) for r in fresh[:10])
        if len(fresh) > 10:
            lines.append(f"   … 외 {len(fresh) - 10}건")
        new_ids = {r["house_manage_no"] for r in fresh}

    opening = [r for r in rows if r["rcept_bgnde"] == today
               and r["house_manage_no"] in known_ids]
    if opening:
        lines.append("🔔 <b>오늘 청약접수 시작</b>")
        lines.extend(_line(r) for r in opening)

    return lines, new_ids


# ── 텔레그램 발송 (deal-radar 패턴) ─────────────────────────────────────
def _split(text: str, limit: int = TG_MAX_LEN) -> list[str]:
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def send_telegram(text: str, token: str, chat_id: str) -> None:
    url = TG_API.format(token=token)
    chunks = _split(text)
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk,
                   "parse_mode": "HTML", "disable_web_page_preview": True}
        for attempt in range(MAX_RETRIES):
            resp = requests.post(url, json=payload, timeout=30)
            if resp.ok:
                break
            if resp.status_code == 429:
                wait = resp.json().get("parameters", {}).get("retry_after", 30)
                time.sleep(wait + 1)
                continue
            raise RuntimeError(f"텔레그램 발송 실패 {resp.status_code}: {resp.text}")
        else:
            raise RuntimeError("텔레그램 발송 실패: 재시도 초과")
        if i < len(chunks) - 1:
            time.sleep(SEND_INTERVAL)


# ── 진입점 ──────────────────────────────────────────────────────────────
FIRST_RUN_LIMIT = 3000  # 첫 실행에서 이보다 많으면 알림 없이 베이스라인만 잡는다


def run_alerts(conn, dry_run: bool = False) -> dict:
    """알림 파이프라인 실행. 반환: 통계 dict."""
    wl = load_watchlist()
    state = load_state()
    since = state.get("last_sale_id", 0)
    rows = new_sales(conn, since)
    today = date.today().isoformat()

    # 청약 소식. 첫 실행(상태에 키 없음)이면 현재 공고 전체를 베이스라인으로
    # 잡고 알림은 생략(과거 공고가 한꺼번에 '신규'로 쏟아지는 것 방지).
    sub_first_run = "known_sub_ids" not in state
    known_subs = set(state.get("known_sub_ids") or [])
    if sub_first_run:
        all_ids = {r["house_manage_no"] for r in conn.execute(
            "SELECT house_manage_no FROM subscription")}
        sub_lines: list[str] = []
        new_sub_ids = all_ids
        if all_ids:
            print(f"[alerts] 청약 첫 실행 - 공고 {len(all_ids)}건 베이스라인 설정")
    else:
        sub_lines, new_sub_ids = subscription_news(
            conn, known_subs, today, watch_gu_names(wl))

    stats = {"new": len(rows), "sub_news": len(sub_lines), "sent": False}
    if not rows and not sub_lines:
        print("[alerts] 신규 거래·청약 소식 없음 - 발송 생략")
        if sub_first_run and new_sub_ids and not dry_run:
            state["known_sub_ids"] = sorted(known_subs | new_sub_ids)
            save_state(state)
        return stats

    # 첫 실행(또는 상태 유실) 시 누적 전체가 '신규'로 잡히는 것을 방지:
    # 알림 없이 현재 최대 id 를 베이스라인으로 저장하고 끝낸다.
    if rows and since == 0 and len(rows) > FIRST_RUN_LIMIT:
        max_id = max(r["id"] for r in rows)
        print(f"[alerts] 첫 실행 - 베이스라인 설정(last_id={max_id}), 발송 생략")
        if not dry_run:
            state["last_sale_id"] = max_id
            state["known_sub_ids"] = sorted(known_subs | new_sub_ids)
            save_state(state)
        return stats

    msg = build_message(conn, wl, rows)
    if sub_lines:
        msg += "\n\n" + "\n".join(sub_lines)

    if dry_run:
        print("[alerts] --dry-run 미리보기 ↓")
        print(msg)
        return stats

    token = config.get_key(config.ENV_TG_TOKEN, required=False)
    chat = config.get_key(config.ENV_TG_CHAT, required=False)
    if not (token and chat):
        print("[alerts] TELEGRAM_BOT_TOKEN/CHAT_ID 없음 - 발송 건너뜀")
        return stats

    send_telegram(msg, token, chat)
    stats["sent"] = True
    if rows:
        state["last_sale_id"] = max(r["id"] for r in rows)
    state["known_sub_ids"] = sorted(known_subs | new_sub_ids)
    save_state(state)
    print(f"[alerts] 발송 완료: 신규 거래 {len(rows)}건, "
          f"청약 소식 {len(sub_lines)}줄")
    return stats
