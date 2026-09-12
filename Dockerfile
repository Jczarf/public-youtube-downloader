FROM node:24-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS web-build

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-fund --no-audit

COPY web/frontend.js ./web/frontend.js
COPY web/static ./web/static
RUN npm run build:web


FROM denoland/deno:bin-2.9.6@sha256:4cf0029b9aeeeed5efcbb71828737f0d7c8c8a20072df960e51a5679ef0d21ba AS deno

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/app-home \
    XDG_CACHE_HOME=/tmp/.cache \
    DENO_DIR=/tmp/deno \
    WEB_FFMPEG_CONCURRENCY=2

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-create-home --uid 10001 app

WORKDIR /app

COPY requirements-web.txt requirements-web.lock.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: "pip==26.2.1" \
    && python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-web.lock.txt \
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

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log"]
