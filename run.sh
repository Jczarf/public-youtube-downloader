#!/usr/bin/env bash
set -euo pipefail

if [ ! -x ".venv/bin/python" ]; then
  echo 'Ambiente virtual não encontrado. Execute ./install.sh primeiro.' >&2
  exit 1
fi

exec .venv/bin/python main.py
