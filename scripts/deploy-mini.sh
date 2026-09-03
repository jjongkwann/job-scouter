#!/usr/bin/env bash
# 미니(mini:~/apps/job-scouter)에 배포한다. origin/main을 pull하고, 리비전이
# 바뀌었을 때만 io·llm·api·web을 재빌드한다(temporal은 건드리지 않는다 —
# 워크플로 이력이 SQLite에 있다). 로그는 deploy/deploy-mini.log 하나에 쌓인다.
#
#   scripts/deploy-mini.sh            # 변경이 있을 때만 재빌드
#   scripts/deploy-mini.sh --force    # 변경이 없어도 재빌드
#   scripts/deploy-mini.sh --status   # 마지막 배포 로그 보기
set -euo pipefail

HOST=mini
REMOTE_DIR=/Users/jk/apps/job-scouter
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOG=$ROOT/deploy/deploy-mini.log
LOCK=$ROOT/deploy/.deploy-mini.lock

FORCE=
case "${1:-}" in
  --status) [ -f "$LOG" ] && exec tail -n 60 "$LOG"; echo "배포 로그 없음"; exit 0 ;;
  --force)  FORCE=1 ;;
  "")       ;;
  *)        echo "사용법: deploy-mini.sh [--force|--status]" >&2; exit 2 ;;
esac

# 동시 배포 방지 — 앞 배포가 도는 중이면 비킨다(그 배포가 최신 main을 가져간다).
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(date '+%F %T')] 배포가 이미 진행 중 — 건너뜀" | tee -a "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

rc=0
{
  echo
  echo "===== $(date '+%F %T') 미니 배포 시작 ${FORCE:+(--force) }====="
  ssh -o ConnectTimeout=10 "$HOST" "FORCE='${FORCE}' REMOTE_DIR='${REMOTE_DIR}' bash -s" <<'REMOTE'
set -euo pipefail
export PATH=/usr/local/bin:/opt/homebrew/bin:$PATH
cd "$REMOTE_DIR"

before=$(git rev-parse HEAD)
git pull --ff-only origin main
after=$(git rev-parse HEAD)

if [ "$before" = "$after" ] && [ -z "$FORCE" ]; then
  echo "변경 없음 ($(git rev-parse --short HEAD)) — 재빌드 생략"
  exit 0
fi

echo "리비전 ${before:0:7} → ${after:0:7}"
docker-compose -f deploy/compose.yaml up -d --build io llm api web
docker-compose -f deploy/compose.yaml ps
REMOTE
} >>"$LOG" 2>&1 || rc=$?

if [ "$rc" -eq 0 ]; then
  echo "===== $(date '+%F %T') 미니 배포 성공 =====" >>"$LOG"
else
  echo "===== $(date '+%F %T') 미니 배포 실패 (exit $rc) =====" >>"$LOG"
fi

tail -n 40 "$LOG"
exit "$rc"
