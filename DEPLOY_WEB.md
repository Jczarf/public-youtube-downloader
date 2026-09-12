# Deploy web — staging seguro no Coolify / VPS

Este documento descreve o primeiro deploy de **staging** do MVP web.

> O staging não deve nascer aberto ao público. Primeiro valide comportamento, consumo e abuso atrás de Cloudflare Access, VPN, allowlist ou outra camada de acesso restrito.

## Fonte

No Coolify, use **Docker Compose from Git** para que as restrições de runtime do repositório sejam aplicadas:

```text
Branch: web-mvp-phase1
Build Pack: Docker Compose
Docker Compose Location: /compose.web.yml
```

Depois do parse, configure no serviço `mediaflow` o domínio apontando para a porta interna 8000, por exemplo:

```text
https://staging.seudominio.com:8000
```

O sufixo `:8000` informa ao proxy qual porta interna usar; o visitante continua acessando HTTPS normalmente. O compose **não publica host port** e o tráfego entra pelo proxy do Coolify.

A imagem inclui Python 3.12, yt-dlp + yt-dlp-ejs, Deno, FFmpeg, FastAPI/Uvicorn e a PWA com Mediabunny lazy-loaded.

As imagens base são fixadas por digest e o frontend usa `package-lock.json` + `npm ci`.

## Variáveis obrigatórias

Substitua o hostname de exemplo pelo domínio real do staging:

```env
WEB_ALLOWED_HOSTS=staging.seudominio.com
WEB_ENABLE_DOCS=0

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

Não coloque cookies do YouTube no primeiro teste.

### Proxy e IP real

Por padrão a aplicação **não confia em X-Forwarded-For**. Isso evita spoofing.

Atrás do Traefik/Coolify, sem configurar proxy confiável, todos os usuários podem ser vistos como o IP do proxy. Para habilitar IP real, descubra a sub-rede exata usada pelo proxy e configure somente essa rede:

```env
WEB_TRUSTED_PROXY_CIDRS=172.18.0.0/24
```

O valor acima é apenas exemplo. **Não use uma faixa ampla por conveniência** e não use `0.0.0.0/0`.

### HTTPS e HSTS

Primeiro confirme que o domínio está funcionando exclusivamente por HTTPS. Depois habilite:

```env
WEB_ENABLE_HSTS=1
```

Não habilite HSTS durante testes em hostname que ainda precise funcionar por HTTP.

## Proteção do staging

Antes do primeiro teste remoto, coloque a aplicação atrás de pelo menos uma destas camadas:

- Cloudflare Access;
- VPN/Tailscale;
- allowlist de IP;
- autenticação no proxy reverso.

Isso evita que scanners automatizados descubram um serviço experimental antes da validação.

## Healthcheck

```text
GET /health
```

Resposta esperada:

```json
{"status":"ok"}
```

Swagger/OpenAPI permanece desabilitado por padrão.

## Recursos iniciais

Use:

- 1 instância;
- 1 worker Uvicorn;
- 1 GiB de memória como limite inicial;
- 2 CPUs como teto inicial;
- no máximo 128 PIDs;
- no máximo 1024 descritores de arquivo soft / 2048 hard;
- filesystem somente leitura;
- todas as Linux capabilities removidas;
- `no-new-privileges`;
- init mínimo para reap de processos filhos;
- `/tmp` em tmpfs limitado;
- sem Redis;
- sem PostgreSQL;
- sem armazenamento persistente.

A sessão de resolução é mantida em memória. Não aumente os workers Uvicorn nesta fase: `/plan`, `/stream` e processamento precisam alcançar o processo que criou a sessão.

Escala horizontal exige estado/limites compartilhados, por exemplo Redis ou outra arquitetura de capability tokens.

## Regras de rede

- exponha apenas o proxy reverso à Internet;
- o `compose.web.yml` usa apenas `expose: 8000`, não `ports:`;
- não publique a porta 8000 diretamente no firewall da VPS;
- não monte `/var/run/docker.sock` no container;
- não monte diretórios do host desnecessários;
- mantenha SSH administrativo restrito por chave/VPN/firewall;
- banco de dados futuro deve ficar em rede privada, nunca com porta pública por padrão.

## Testes de staging

Execute nesta ordem:

1. confirmar que acesso sem a camada privada/Access é bloqueado;
2. confirmar HTTPS;
3. testar Host header inválido;
4. confirmar que `/docs` e `/openapi.json` retornam 404;
5. abrir a PWA no desktop e celular;
6. testar vídeo curto 360p/720p;
7. testar direct-first e fallback relay;
8. testar 1080p adaptativo;
9. testar merge local pequeno;
10. forçar fallback FFmpeg;
11. testar MP3;
12. testar um vídeo acima do limite e confirmar recusa;
13. testar excesso de requisições e confirmar 429/503;
14. repetir operações concorrentes;
15. observar CPU, RAM, PIDs, conexões e tráfego;
16. registrar respostas 403/429 do YouTube.

## Métricas mínimas

Registre, sem armazenar URLs assinadas nem IDs de sessão completos:

```text
resoluções
resoluções recusadas por limite
429 por endpoint
503 por capacidade
direct-first tentado/sucesso
relay utilizado
merge local sucesso/falha
FFmpeg merge
MP3
tempo de resolução
bytes transmitidos
HTTP 403/429 upstream
falhas do FFmpeg
uso máximo de CPU/RAM/PIDs
```

## Antes de abrir ao público

Ainda é obrigatório adicionar proteção distribuída de edge. O limitador interno é uma segunda camada, não substitui WAF/CDN:

- rate limiting no Cloudflare ou equivalente;
- bot protection / Turnstile quando fizer sentido;
- alertas de CPU, RAM, banda e egress;
- limite de custo/transferência no provedor se disponível;
- telemetria de abuso;
- política de privacidade e termos;
- processo de atualização de yt-dlp, FFmpeg, imagens base e dependências.

Não crie contas, planos ou pagamentos antes de medir o custo real por download e a taxa de bloqueio do YouTube.

## Atualização

Deploys devem ser reconstruídos a partir do Git commit. Não instale pacotes manualmente dentro do container em produção.

Quando atualizar uma imagem base fixada por digest, trate a alteração como atualização de dependência: rode CI, Trivy, Security Audit e smoke tests antes de promover.
