#!/usr/bin/env bash
set -euo pipefail
MCP_RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$MCP_RUNTIME_DIR"
# The integration stays local; do not send SDK usage telemetry.
export MCP_USE_ANONYMIZED_TELEMETRY=false
if [[ -x "$MCP_RUNTIME_DIR/../agent-runtime/node_modules/node/bin/node" ]]; then
  export PATH="$MCP_RUNTIME_DIR/../agent-runtime/node_modules/node/bin:$PATH"
fi
if [[ "$(node -p 'Number(process.versions.node.split(".")[0])')" -lt 24 ]]; then
  printf '%s\n' 'The local MCP adapter requires Node 24+. Install the agent-runtime dependencies first.' >&2
  exit 1
fi
MCP_COMMAND="${1:-dev}"
shift || true
case "$MCP_COMMAND" in
  dev) exec node --env-file-if-exists=.env --import tsx src/start.ts "$@" ;;
  start) exec node --env-file-if-exists=.env dist/src/start.js "$@" ;;
  build) exec node node_modules/typescript/bin/tsc "$@" ;;
  typecheck) exec node node_modules/typescript/bin/tsc --noEmit "$@" ;;
  test) exec node --import tsx --test tests/*.test.ts "$@" ;;
  demo) exec node --env-file-if-exists=.env --import tsx scripts/multiple-clients.ts "$@" ;;
  eval) exec node --env-file-if-exists=.env ../evals/run.mjs "$@" ;;
  *) printf 'Unknown MCP command: %s\n' "$MCP_COMMAND" >&2; exit 1 ;;
esac
