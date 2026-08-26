#!/usr/bin/env bash
set -euo pipefail

printf 'YouTube Downloader — instalação\n'

if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 não encontrado.' >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ é necessário.')
PY

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo 'Aviso: FFmpeg não encontrado. Conversão, merge e recortes exigem FFmpeg.' >&2
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo 'Instalação concluída. Execute: ./run.sh'
