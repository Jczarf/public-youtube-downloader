# Web MVP — pipeline funcional

A branch adiciona uma versão web/PWA sem remover ou alterar a aplicação desktop existente.

## Fluxo atual

```text
usuário no navegador
        ↓
POST /api/v1/resolve
        ↓
yt-dlp resolve formatos
        ↓
sessão efêmera (10 min)
        ↓
POST /api/v1/plan
        ↓
┌───────────────────────────────────────────┐
│ formato progressivo                      │
│ direct-first → relay como fallback       │
└───────────────────────────────────────────┘
                    ou
┌───────────────────────────────────────────┐
│ vídeo + áudio separados                  │
│ processamento local: próxima otimização  │
│ FFmpeg streaming na VPS: fallback atual  │
└───────────────────────────────────────────┘
```

Nenhum endpoint aceita uma URL arbitrária para proxy. As URLs reais do CDN são mantidas na sessão do servidor.

## Interface

A raiz `/` serve uma PWA responsiva, pensada para celular e desktop.

Ela permite:

- colar um link;
- escolher Vídeo ou MP3;
- selecionar qualidade de vídeo;
- visualizar thumbnail, título e duração;
- usar automaticamente a rota planejada pelo backend;
- recorrer ao modo compatível quando o direct-first não funcionar;
- instalar o shell como PWA em navegadores compatíveis.

O service worker armazena apenas os arquivos estáticos da interface. Rotas `/api/` e arquivos de mídia não entram no cache da PWA.

## Executar

```bash
./run-web.sh
```

Depois abra:

```text
http://localhost:8000/
```

Swagger:

```text
http://localhost:8000/docs
```

## API

### Resolver

```http
POST /api/v1/resolve

{
  "url": "https://www.youtube.com/watch?v=..."
}
```

### Planejar

```http
POST /api/v1/plan

{
  "session_id": "...",
  "media_type": "video",
  "quality": 1080
}
```

O planejador prefere um único stream progressivo quando ele atende à qualidade. Para qualidades adaptativas, escolhe vídeo e áudio separados.

### Direct-first

```http
GET /api/v1/direct/{session_id}/{candidate_id}
```

Disponível apenas para HTTPS em `googlevideo.com` e quando a fonte não exige headers sensíveis. É uma otimização oportunista; o relay continua disponível como fallback.

### Relay

```http
GET /api/v1/stream/{session_id}/{candidate_id}
Range: bytes=0-
```

Encaminha `Range` e repassa headers relevantes de resposta. O conteúdo passa pela VPS sem precisar ser salvo integralmente em disco.

### Merge MP4 no servidor

```http
GET /api/v1/merge/{session_id}/{video_id}/{audio_id}
```

Para o fallback inicial, vídeo MP4 + áudio M4A/MP4 são unidos por FFmpeg com stream copy. O resultado sai por `pipe:1` como MP4 fragmentado; não há arquivo temporário completo.

### Converter áudio para MP3

```http
GET /api/v1/convert/audio/{session_id}/{candidate_id}?bitrate=192
```

Converte em streaming para MP3, entre 64 e 320 kbps.

## Controle de carga

O número máximo de processos FFmpeg simultâneos é controlado por:

```bash
WEB_FFMPEG_CONCURRENCY=2
```

O padrão é 2 e o código limita o valor a no máximo 8. Para o primeiro deploy, manter 2 é intencional.

## Segurança

- somente links diretos reconhecidos do YouTube no resolver inicial;
- sem open proxy/SSRF: nenhuma URL de origem é recebida do cliente nos endpoints de stream;
- URLs do CDN ficam somente no servidor;
- sessões expiram em 10 minutos;
- direct-first restrito a `googlevideo.com`;
- direct-first recusado com `Cookie`, `Authorization` ou `Proxy-Authorization`;
- headers repassados ao FFmpeg têm CR/LF filtrados;
- subprocessos FFmpeg usam `create_subprocess_exec`, sem shell;
- concorrência de FFmpeg limitada;
- relay suporta HTTP Range;
- PWA não cacheia API nem mídia;
- `pip-audit` audita o conjunto completo de dependências web.

## Dependências web

A baseline de segurança atual inclui:

```text
FastAPI 0.141.1
Starlette 1.6.0
HTTPX 0.28.1
Uvicorn 0.52.4
```

O pin explícito do Starlette evita resolver versões antigas com vulnerabilidades conhecidas.

## Próximos passos

1. validar o pipeline real na VPS/Coolify;
2. adicionar processamento/remux local no navegador;
3. medir taxa real de direct-first vs relay vs FFmpeg;
4. adicionar rate limit, limites de duração/tamanho e proteção antiabuso;
5. Docker/Coolify com healthcheck;
6. só então autenticação, planos e pagamentos.
