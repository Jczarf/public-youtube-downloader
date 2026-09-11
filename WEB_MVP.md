# Web MVP — pipeline híbrido e baseline segura

Esta branch adiciona a versão web/PWA sem remover a aplicação desktop.

## Fluxo

```text
navegador
  ↓
POST /api/v1/resolve
  ↓
yt-dlp
  ↓
sessão efêmera em memória
  ↓
POST /api/v1/plan
  ↓
progressivo ── direct-first → relay
       ou
adaptativo ── merge local no navegador
                    ↓ fallback
              FFmpeg na VPS
```

A API não aceita uma URL arbitrária como destino de proxy. URLs de mídia usadas pelo servidor precisam passar pela allowlist HTTPS de `googlevideo.com`.

## Executar localmente

Requer Python 3.12 e npm:

```bash
./run-web.sh
```

O bind local padrão é:

```text
http://127.0.0.1:8000/
```

Swagger/OpenAPI/ReDoc ficam **desabilitados por padrão**. Para depuração local consciente:

```bash
WEB_ENABLE_DOCS=1 ./run-web.sh
```

## Rotas principais

- `POST /api/v1/resolve`: resolve um link direto de vídeo do YouTube.
- `POST /api/v1/plan`: escolhe estratégia/formato.
- `GET /api/v1/direct/{session}/{candidate}`: tentativa direta via CDN.
- `GET /api/v1/stream/{session}/{candidate}`: relay com Range.
- `GET /api/v1/merge/{session}/{video}/{audio}`: fallback MP4/FFmpeg.
- `GET /api/v1/convert/audio/{session}/{candidate}`: MP3/FFmpeg.
- `GET /health`: somente `{"status":"ok"}`.

## Merge local

Para combinações MP4 + M4A/MP4 pequenas, a PWA carrega Mediabunny sob demanda e tenta unir as faixas no dispositivo.

O limite local atual é de aproximadamente **80 MiB estimados**. Acima disso, ou em erro/indisponibilidade, o plano usa o fallback permitido no servidor.

Mediabunny não fica no bundle inicial; o chunk pesado é carregado apenas quando necessário.

## Limites padrão do servidor

```env
WEB_FFMPEG_CONCURRENCY=2
WEB_FFMPEG_TIMEOUT_SECONDS=3600
WEB_RESOLVE_CONCURRENCY=4
WEB_RELAY_CONCURRENCY=8

WEB_ACTIVE_RESOLVE_PER_CLIENT=1
WEB_ACTIVE_PROCESS_PER_CLIENT=1
WEB_ACTIVE_RELAY_PER_CLIENT=6

WEB_RATE_RESOLVE_PER_MINUTE=8
WEB_RATE_PLAN_PER_MINUTE=30
WEB_RATE_PROCESS_PER_MINUTE=6
WEB_RATE_RELAY_PER_MINUTE=180
WEB_RATE_DIRECT_PER_MINUTE=60

WEB_MAX_DURATION_SECONDS=7200
WEB_MAX_MEDIA_BYTES=1073741824
WEB_MAX_SESSIONS=256
WEB_MAX_CANDIDATES_PER_SESSION=64
```

São defesas de aplicação, não substitutos para rate limiting/WAF no edge.

## Segurança relevante

A implementação atual inclui:

- canonicalização do link de entrada;
- allowlist positiva de host/protocolo para mídia;
- redirects HTTP manuais, limitados e revalidados;
- HTTPX sem confiança em proxies de ambiente;
- allowlist de headers enviados à origem;
- limites de corpo HTTP antes de Pydantic/yt-dlp;
- validação de Range;
- limites de bytes, duração, sessões e candidatos;
- rate limit e limites de operações ativas por cliente;
- admissão fail-fast para resolução, relay e FFmpeg;
- FFmpeg sem shell, com protocolos permitidos, timeout e ambiente mínimo;
- Swagger/OpenAPI desligados por padrão;
- TrustedHost;
- CSP, anti-frame, nosniff, no-referrer e Permissions Policy;
- bloqueio de requisições browser cross-site à API;
- access log do Uvicorn desligado para não registrar capability IDs;
- container não root, read-only, sem capabilities e com recursos limitados no Compose;
- dependências Node travadas por `package-lock.json`;
- dependências Python web travadas por `requirements-web.lock.txt` com hashes;
- imagens base do Docker fixadas por digest;
- `npm audit`, `pip-audit`, scanner de secrets, Trivy e CodeQL.

O modelo completo, riscos residuais e orientações operacionais estão em `SECURITY.md`.

## Build frontend

```bash
npm ci --ignore-scripts
npm run build:web
```

O código-fonte é `web/frontend.js`. `web/static/app.js` e `web/static/chunks/` são artefatos gerados e não ficam versionados.

## Deploy

Para staging no Coolify, use `compose.web.yml` via **Docker Compose from Git**, não um deploy Dockerfile simplificado. Isso garante que os controles de runtime do Compose sejam aplicados.

Veja `DEPLOY_WEB.md`.

## Próximos gates

1. todos os checks do commit final verdes;
2. staging privado atrás de proxy/Access/VPN;
3. validar comportamento real do YouTube/IP da VPS;
4. medir CPU, RAM, PIDs, egress, 403/429 e taxas de fallback;
5. adicionar proteção distribuída de edge antes de abertura pública;
6. só depois considerar autenticação, planos e pagamentos.
