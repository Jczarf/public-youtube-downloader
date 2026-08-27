#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -x ".venv/bin/python" ]; then
  echo 'Ambiente virtual não encontrado. Execute ./install.sh primeiro.' >&2
  exit 1
fi

exec .venv/bin/python main.py
