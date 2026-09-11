# Web MVP — Fase 1

Esta branch adiciona uma camada web sem remover ou alterar a aplicação desktop.

## Objetivo

Validar o primeiro trecho da arquitetura:

```text
cliente
  ↓
POST /api/v1/resolve
  ↓
yt-dlp resolve formatos
  ↓
sessão efêmera no servidor
  ↓
GET /api/v1/stream/{sessão}/{formato}
  ↓
relay HTTP com suporte a Range
```

A URL real do CDN não é devolvida pela API. Isso evita expor tokens temporários e também impede que o endpoint de stream seja usado como proxy arbitrário.

## Executar

```bash
./run-web.sh
```

ou:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-web.txt
.venv/bin/uvicorn web.app:app --reload
```

Swagger:

```text
http://localhost:8000/docs
```

## Endpoints

### Health

```http
GET /health
```

### Resolver um vídeo

```http
POST /api/v1/resolve
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=..."
}
```

A resposta inclui os formatos disponíveis e classifica a sessão para os próximos caminhos:

- formato progressivo: pode ser retransmitido imediatamente;
- vídeo + áudio separados: candidato para merge no navegador;
- vídeo + áudio separados: também marca a necessidade de fallback FFmpeg no servidor.

### Transmitir um formato

```http
GET /api/v1/stream/{session_id}/{candidate_id}
Range: bytes=0-
```

O relay encaminha o header `Range` para a origem e repassa headers relevantes como `Content-Range`, `Accept-Ranges` e `Content-Length`.

## Segurança já aplicada

- aceita somente links diretos reconhecidos do YouTube;
- não existe endpoint de proxy para URL arbitrária;
- URLs reais de mídia ficam somente no servidor;
- sessões expiram após 10 minutos;
- somente formatos HTTP/HTTPS resolvidos pelo yt-dlp entram no relay.

## Próximas fases

1. endpoint de seleção de melhor formato;
2. tentativa direct-first controlada;
3. merge local no navegador para vídeo/áudio adaptativos;
4. fallback FFmpeg streaming no servidor;
5. rate limit, Turnstile e limites de tamanho/duração;
6. PWA/React responsiva para desktop e celular;
7. Docker/Coolify para deploy na VPS.
