# Deploy web — Coolify / VPS

Este documento descreve o primeiro deploy de **staging** do MVP web.

> Não exponha a aplicação para tráfego público amplo antes de adicionar rate limit e proteção antiabuso. O objetivo inicial é validar o comportamento real do YouTube a partir do IP da VPS.

## Fonte

No Coolify, crie uma nova aplicação a partir deste repositório e use:

```text
Branch: web-mvp-phase1
Build Pack: Dockerfile
Dockerfile: /Dockerfile
Porta interna: 8000
```

A imagem inclui:

- Python 3.12;
- yt-dlp + yt-dlp-ejs;
- Deno;
- FFmpeg;
- FastAPI/Uvicorn;
- PWA estática;
- bundle Mediabunny para merge local no navegador.

## Variáveis

Comece somente com:

```env
WEB_FFMPEG_CONCURRENCY=2
WEB_RESOLVE_CONCURRENCY=4
WEB_RELAY_CONCURRENCY=8
WEB_MAX_DURATION_SECONDS=7200
```

Não coloque cookies do YouTube no primeiro teste.

## Healthcheck

```text
GET /health
```

Resposta esperada:

```json
{"status":"ok","version":"0.3.0"}
```

## Recursos iniciais

Para staging:

- 1 instância;
- 1 processo Uvicorn;
- `WEB_FFMPEG_CONCURRENCY=2`;
- no máximo 4 resoluções simultâneas;
- no máximo 8 requests de relay ativos;
- vídeos limitados a 2 horas (`7200` s) no staging;
- sem Redis;
- sem PostgreSQL;
- sem armazenamento persistente.

A sessão de resolução é mantida em memória. Por isso **não aumente o número de workers Uvicorn nesta fase**: uma requisição `/plan` ou `/stream` precisa chegar ao mesmo processo que criou a sessão.

Quando houver necessidade de escala horizontal, a sessão efêmera deverá migrar para Redis ou ser substituída por tokens de sessão assinados.

## Testes de staging

Execute, nesta ordem:

1. abrir a página principal no desktop;
2. abrir no Android/iOS;
3. testar um vídeo público curto em 360p/720p;
4. testar direct-first;
5. testar o botão de modo compatível/relay;
6. testar 1080p, que normalmente exige faixas adaptativas;
7. confirmar em um vídeo pequeno que aparece a rota de processamento no dispositivo;
8. testar o fallback automático para FFmpeg no servidor;
9. testar MP3;
10. repetir com duas operações simultâneas;
11. observar CPU, RAM e tráfego;
12. registrar erros HTTP 403/429 do YouTube.

## Métricas mínimas a registrar

Antes de monetização, precisamos saber:

```text
resoluções solicitadas
direct-first tentado
direct-first efetivamente útil
relay utilizado
merge local utilizado
merge local falhou
FFmpeg merge utilizado
MP3 utilizado
tempo de resolução
bytes transmitidos
HTTP 403
HTTP 429
falhas do FFmpeg
```

Essas métricas vão determinar se vale investir primeiro em processamento local no navegador, novos workers ou otimização de rede.

## Observações de segurança

O MVP já evita open proxy e não expõe URLs reais do CDN no JSON. Ainda faltam, antes de abrir ao público:

- rate limit por IP/sessão;
- limite de tamanho estimado;
- limite global de streams já existe no processo, mas ainda falta coordenação distribuída quando houver múltiplas instâncias;
- proteção de origem/proxy confiável;
- Cloudflare Turnstile ou mecanismo equivalente;
- telemetria de abuso;
- timeouts e quotas por plano;
- política de privacidade/termos de uso.

## Atualização

O deploy deve ser construído novamente a partir do Git commit. Não instale dependências manualmente dentro do container em produção.
