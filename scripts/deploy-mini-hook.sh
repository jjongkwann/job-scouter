#!/usr/bin/env bash
# Claude Code PostToolUse(Bash) 훅 — Bash로 실행한 명령에 `git push`가 있으면
# 미니 배포를 백그라운드로 띄운다. push가 실패했으면 원격 리비전이 그대로라
# deploy-mini.sh가 "변경 없음"으로 빠져나온다(재빌드 없음).
set -euo pipefail

# 실제로 실행된 `git push`만 — 문자열로 언급만 한 명령은 걸리지 않게 줄 첫머리
# 또는 구분자(; && | () 뒤에 오는 것만 본다.
cmd=$(jq -r '.tool_input.command // ""')
printf '%s\n' "$cmd" | grep -Eq '(^|[;&|(])[[:space:]]*git[[:space:]]+push([[:space:]]|$)' || exit 0

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
nohup "$ROOT/scripts/deploy-mini.sh" >/dev/null 2>&1 &

jq -nc '{hookSpecificOutput: {hookEventName: "PostToolUse",
  additionalContext: "미니 배포를 백그라운드로 시작했다. 결과 확인: scripts/deploy-mini.sh --status"}}'
