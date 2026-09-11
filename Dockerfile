FROM node:24-bookworm-slim AS web-build

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-fund --no-audit

COPY web/frontend.js ./web/frontend.js
COPY web/static ./web/static
RUN npm run build:web


FROM denoland/deno:bin-2.9.6 AS deno

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_FFMPEG_CONCURRENCY=2

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app

COPY requirements-web.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-web.txt \
    && python -m pip check \
    && deno --version \
    && python -c "import yt_dlp, yt_dlp_ejs"

COPY src ./src
COPY web ./web
COPY --from=web-build /build/web/static ./web/static

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
