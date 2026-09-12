#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
WEB_BIND_HOST="${WEB_BIND_HOST:-127.0.0.1}"

if ! command -v npm >/dev/null 2>&1; then
  echo "Erro: npm é obrigatório para gerar o frontend web a partir do código-fonte." >&2
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --only-binary=:all: "pip==26.2.1"
.venv/bin/python -m pip install   --only-binary=:all:   --require-hashes   -r requirements-web.lock.txt

npm ci --ignore-scripts --no-fund --no-audit
npm run build:web

exec .venv/bin/python -m uvicorn web.app:app   --host "$WEB_BIND_HOST"   --port "${PORT:-8000}"   --no-server-header   --no-access-log
