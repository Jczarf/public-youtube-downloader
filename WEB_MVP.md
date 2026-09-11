# Web MVP — Fases 1 e 2

A branch adiciona uma camada web sem remover ou alterar a aplicação desktop.

## Arquitetura atual

```text
cliente
  ↓
POST /api/v1/resolve
  ↓
yt-dlp resolve formatos
  ↓
sessão efêmera
  ↓
POST /api/v1/plan
  ↓
┌───────────────────────────────┐
│ progressivo                   │
│ direct-first → relay fallback │
└───────────────────────────────┘
              ou
┌───────────────────────────────┐
│ vídeo + áudio separados       │
│ browser-merge                 │
│ FFmpeg servidor: próxima fase │
└───────────────────────────────┘
```

As URLs reais do CDN não aparecem no JSON da API. O direct-first usa um endpoint efêmero que só redireciona para formatos previamente resolvidos pelo yt-dlp. Não existe proxy para URL arbitrária.

## Executar

```bash
./run-web.sh
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

### Resolver

```http
POST /api/v1/resolve
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=..."
}
```

A resposta contém metadados, formatos públicos e as capacidades detectadas.

### Criar plano de download

```http
POST /api/v1/plan
Content-Type: application/json

{
  "session_id": "...",
  "media_type": "video",
  "quality": 1080
}
```

O planejador:

1. prefere um formato progressivo quando ele já atende à qualidade desejada;
2. tenta `direct-first` apenas em URLs HTTPS do domínio `googlevideo.com` e sem headers sensíveis;
3. sempre informa o relay como fallback para um formato progressivo;
4. escolhe vídeo e áudio separados quando isso oferece qualidade superior;
5. prefere MP4 + M4A para facilitar o merge no navegador.

Para áudio, a Fase 2 entrega a melhor fonte compatível. Conversão real para MP3 entra junto do processamento local/fallback FFmpeg.

### Tentativa direta

```http
GET /api/v1/direct/{session_id}/{candidate_id}
```

Retorna um redirect temporário para o CDN. É oportunista: IP binding, headers ou tokens podem fazer essa tentativa falhar no dispositivo do usuário. Nesse caso, o frontend deve usar o `relay_url` do plano.

### Relay

```http
GET /api/v1/stream/{session_id}/{candidate_id}
Range: bytes=0-
```

O relay encaminha `Range` para a origem e repassa headers relevantes como `Content-Range`, `Accept-Ranges` e `Content-Length`.

## Segurança aplicada

- somente links diretos reconhecidos do YouTube no resolver inicial;
- nenhum endpoint aceita uma URL de proxy fornecida pelo usuário;
- URL de origem fica armazenada na sessão efêmera do servidor;
- sessão expira em 10 minutos;
- direct-first limitado a HTTPS em `googlevideo.com`;
- direct-first bloqueado se a fonte exigir `Cookie`, `Authorization` ou `Proxy-Authorization`;
- relay somente para candidatos criados pelo yt-dlp;
- formatos HLS/DASH ficam fora do relay nesta fase.

## Próximas fases

1. merge local no navegador para vídeo/áudio adaptativos;
2. fallback FFmpeg em streaming no servidor;
3. PWA/React responsiva;
4. rate limit, Turnstile e limites de tamanho/duração;
5. Docker/Coolify para deploy na VPS;
6. telemetria de estratégia: taxa de direct, relay e fallback;
7. autenticação/planos somente depois do pipeline validado.
