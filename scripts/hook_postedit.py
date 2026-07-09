"""Claude Code PostToolUse 훅 - seoul-apt docs 자산 편집 시 자동 처리.

Edit/Write 후 호출되어(stdin JSON) 대상이 seoul-apt/docs 자산이면:
  1) docs/*.html 안의 '<파일명>?v=N' 캐시버전을 N+1로 자동 증가
     (브라우저 구버전 캐시로 인한 "고쳤는데 안 바뀜" 오탐 방지)
  2) .js 파일이면 node --check 문법 검사 - 실패 시 exit 2(Claude에 피드백)

seoul-apt 외 경로는 즉시 무시(exit 0). 훅 자체 오류로 편집을 막지 않도록
방어적으로 동작한다. 등록: ~/.claude/settings.json PostToolUse(Edit|Write).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"   # seoul-apt/docs


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    fp = (payload.get("tool_input") or {}).get("file_path") or ""
    try:
        path = Path(fp).resolve()
    except Exception:
        return 0

    # seoul-apt/docs/js·css 자산만 대상
    try:
        rel = path.relative_to(DOCS)
    except ValueError:
        return 0
    if rel.parts[0] not in ("js", "css"):
        return 0
    # config.js는 export가 생성(캐시버전 없음), html 자신은 무시
    if path.name == "config.js":
        return 0

    bump_versions(path.name)

    if path.suffix == ".js":
        r = subprocess.run(["node", "--check", str(path)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(f"[hook] JS 문법 오류 {path.name}:\n{r.stderr}")
            return 2   # Claude에게 차단 피드백
    return 0


def bump_versions(asset_name: str) -> None:
    """docs/*.html 에서 asset_name?v=N → N+1 (참조하는 페이지 전부)."""
    pat = re.compile(re.escape(asset_name) + r"\?v=(\d+)")
    for html in DOCS.glob("*.html"):
        try:
            text = html.read_text(encoding="utf-8")
        except Exception:
            continue
        new, n = pat.subn(
            lambda m: f"{asset_name}?v={int(m.group(1)) + 1}", text)
        if n:
            html.write_text(new, encoding="utf-8")
            print(f"[hook] {html.name}: {asset_name} ?v= +1")


if __name__ == "__main__":
    sys.exit(main())
