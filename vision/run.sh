#!/usr/bin/env bash
# Valve inspection pipeline: capture -> jepa -> explain (dry run unless --live-explain) -> POST to backend.
#
#   vision/run.sh <site> [--defect TAG=kind ...] [--source capture|eye] [--renderer swiftshader|gpu]
#                        [--live-explain] [--skip-capture] [--no-post]
#                        [--base http://127.0.0.1:3000] [--backend http://127.0.0.1:8001]
#
# Example: vision/run.sh myer-plant --defect V-503=leak --source eye
# The site engineer (myer-engineer / bristol-engineer) is the actor for the eye, the results and the POST.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"
[[ -x "$PY" ]] || { echo "vision/.venv missing; see vision/README.md (setup)" >&2; exit 2; }

[[ $# -ge 1 && "$1" != -* ]] || { sed -n '2,9p' "$0" >&2; exit 2; }
SITE="$1"; shift
BASE="${STEWARD_FRONTEND:-http://127.0.0.1:3000}"
BACKEND="${STEWARD_BACKEND:-http://127.0.0.1:8001}"
CAPTURE_ARGS=(); EXPLAIN_ARGS=(); SKIP_CAPTURE=0; POST=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --defect) CAPTURE_ARGS+=(--defect "$2"); shift 2 ;;
    --defect=*) CAPTURE_ARGS+=(--defect "${1#--defect=}"); shift ;;
    --source|--renderer|--timeout|--assets-file|--only) CAPTURE_ARGS+=("$1" "$2"); shift 2 ;;
    --live-explain) EXPLAIN_ARGS+=(--live); shift ;;
    --skip-capture) SKIP_CAPTURE=1; shift ;;
    --no-post) POST=0; shift ;;
    --base) BASE="$2"; shift 2 ;;
    --backend) BACKEND="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

t0=$(date +%s)
if [[ $SKIP_CAPTURE -eq 0 ]]; then
  echo "== capture ($SITE)"
  "$PY" "$HERE/capture.py" "$SITE" --base "$BASE" --backend "$BACKEND" ${CAPTURE_ARGS[@]+"${CAPTURE_ARGS[@]}"}
fi
echo "== jepa ($SITE)"
"$PY" "$HERE/jepa.py" "$SITE"
echo "== explain ($SITE)"
"$PY" "$HERE/explain.py" "$SITE" --backend "$BACKEND" ${EXPLAIN_ARGS[@]+"${EXPLAIN_ARGS[@]}"}
if [[ $POST -eq 1 ]]; then
  echo "== post ($SITE)"
  rc=0; "$PY" "$HERE/post.py" "$SITE" --backend "$BACKEND" || rc=$?
  if [[ $rc -eq 3 ]]; then echo "(backend ingest route missing; results kept in vision/results/$SITE.json)";
  elif [[ $rc -ne 0 ]]; then exit $rc; fi
fi
echo "== done in $(( $(date +%s) - t0 ))s -> vision/results/$SITE.json"
