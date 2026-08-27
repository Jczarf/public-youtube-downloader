#!/usr/bin/env bash
set -euo pipefail

printf 'YouTube Downloader — instalação\n'

if [ -n "${PYTHON_BIN:-}" ]; then
  PYTHON="$PYTHON_BIN"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON="python3.12"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo 'Python 3 não encontrado.' >&2
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ é necessário.')
print(f'Python detectado: {sys.version.split()[0]}')
if sys.version_info[:2] != (3, 12):
    print('Aviso: a baseline principal do CI usa Python 3.12; esta versão ainda pode funcionar, mas não é a baseline de referência.')
PY

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo 'Aviso: FFmpeg não encontrado. Conversão, merge e recortes exigem FFmpeg.' >&2
fi

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo 'Instalação concluída.'
echo 'Execute: ./run.sh'
echo 'Alternativa: .venv/bin/python main.py'
