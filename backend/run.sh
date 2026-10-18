#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/steward-uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$(pwd)/../.runtime/python}"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -r requirements.txt
exec .venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port "${BACKEND_PORT:-8001}"
