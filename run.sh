#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo 'Ambiente virtual não encontrado. Execute ./install.sh primeiro.' >&2
  exit 1
fi

. .venv/bin/activate
exec python main.py
