#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if [[ ! -x ".venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install -r requirements-web.txt
exec .venv/bin/python -m uvicorn web.app:app --host 0.0.0.0 --port "${PORT:-8000}"
