#!/usr/bin/env bash
# 누적 원천 DB(data/seoul_apt.sqlite)를 GitHub Release 자산으로 저장/복원한다.
# GitHub 트리는 파일 100MB 제한이 있어, 대용량 DB는 Release 자산으로 둔다.
#
#   scripts/db_release.sh pull   # Release → 로컬 (수집 전)
#   scripts/db_release.sh push   # 로컬 → Release (export 후)
#
# 필요: gh CLI + 인증(GH_TOKEN 또는 로컬 gh auth). 태그 db-latest 사용.
set -euo pipefail

TAG="db-latest"
DB="data/seoul_apt.sqlite"
ASSET="seoul_apt.sqlite"

cmd="${1:-}"
case "$cmd" in
  pull)
    mkdir -p data
    if gh release download "$TAG" --pattern "$ASSET" --dir data --clobber 2>/dev/null; then
      echo "[db_release] pull 완료: $DB ($(du -h "$DB" | cut -f1))"
    else
      echo "[db_release] 기존 Release 없음 - 빈 DB로 시작"
    fi
    ;;
  push)
    if [ ! -f "$DB" ]; then echo "[db_release] $DB 없음"; exit 1; fi
    if ! gh release view "$TAG" >/dev/null 2>&1; then
      gh release create "$TAG" --title "DB snapshot" \
        --notes "seoul_apt.sqlite 누적 원천 DB (자동 갱신). 코드가 아니라 데이터 스냅샷입니다."
    fi
    gh release upload "$TAG" "$DB" --clobber
    echo "[db_release] push 완료: $DB ($(du -h "$DB" | cut -f1)) → release $TAG"
    ;;
  *)
    echo "usage: $0 {pull|push}"; exit 2 ;;
esac
