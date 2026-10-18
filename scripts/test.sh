#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && .venv/bin/python -m pytest -q)
agent-runtime/node_modules/node/bin/node --test agent-runtime/tests/scope.test.mjs
npm --prefix mcp-runtime test
npm --prefix mcp-runtime run build
npm --prefix frontend run typecheck
npm --prefix frontend run build
