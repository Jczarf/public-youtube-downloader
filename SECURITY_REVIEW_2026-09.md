# Security review — setembro de 2026

Escopo: branch `web-mvp-phase1`, antes do primeiro staging público.

Este documento é uma revisão adversarial do MVP web. Ele não substitui testes de penetração, monitoramento ou revisão contínua. O objetivo é registrar decisões de segurança e impedir que otimizações futuras reintroduzam classes de falhas já conhecidas.

## Princípio

O serviço deve assumir que são não confiáveis:

- o link informado pelo usuário;
- metadados, títulos, thumbnails e formatos retornados pela origem;
- bytes de mídia;
- headers e redirects remotos;
- clientes HTTP e seus headers;
- conteúdo lido por agentes de desenvolvimento;
- pull requests e atualizações de dependências;
- respostas de ferramentas/MCP usadas por agentes.

## Padrões observados em incidentes recentes

### 1. Autorização não pode depender de identificadores ou estado do cliente

O incidente da Base44 mostrou que um identificador de aplicação não secreto foi suficiente para alcançar endpoints de registro/verificação e contornar controles de aplicações privadas. O incidente da Lovable mostrou como uma regressão de backend reabriu dados que o produto já pretendia manter privados.

Regra para este projeto quando contas/planos forem adicionados:

- autorização sempre no servidor, em toda requisição;
- negar por padrão;
- nunca considerar `user_id`, `app_id`, `plan`, `role`, flags do frontend ou parâmetros de URL como prova de autorização;
- testes negativos obrigatórios para acesso cruzado entre usuários/tenants;
- se PostgreSQL/Supabase for usado, RLS deny-by-default e service-role nunca no navegador.

### 2. Agentes não podem promover sua própria alteração de segurança

Incidentes e pesquisas envolvendo Cursor/MCP demonstraram que conteúdo de repositório pode influenciar agentes e transformar arquivos de configuração em execução de código. Ataques ao ecossistema MCP demonstraram também o risco de ferramentas legítimas serem combinadas para atravessar fronteiras de dados.

Regra para este projeto:

- agentes podem propor mudanças, mas arquivos de CI, dependências, container, auth e segurança exigem revisão humana;
- não conceder ao agente token capaz de modificar branch protection/rulesets/secrets;
- não executar comandos vindos de issues, README, páginas web ou resultados de ferramenta sem revisão;
- nenhum deploy automático a produção a partir de código não revisado;
- CODEOWNERS identifica as superfícies sensíveis; o ruleset do GitHub deve tornar essa revisão obrigatória.

### 3. Supply chain é parte da superfície de ataque

Dependências, GitHub Actions, imagens e ferramentas de build são código com privilégio de execução.

Controles atuais:

- imagens base por digest;
- Actions por commit SHA;
- `npm ci --ignore-scripts`;
- grafo npm versionado;
- requirements web com hashes;
- `pip-audit`, `npm audit`, CodeQL, Trivy e scanner de secrets;
- Dependabot para Python, npm, Actions e Docker.

Não adicionar dependência somente porque foi sugerida por IA. Toda nova dependência deve justificar função, manutenção, licença e superfície de execução.

## Ataques considerados contra o MVP atual

| Vetor | O que um atacante tentaria | Controle atual | Residual |
|---|---|---|---|
| SSRF / metadata | transformar a VPS em cliente de `localhost`, RFC1918 ou `169.254.169.254` | URL de entrada canonicalizada; fetch de mídia somente HTTPS em `googlevideo.com`; redirects revalidados; porta 443; sem credenciais na URL; `trust_env=False` | bug futuro no extractor/parser ou comprometimento de DNS/infra |
| Open proxy | usar `/stream` para buscar URL arbitrária | cliente nunca fornece URL de origem; somente IDs efêmeros resolvidos pelo servidor | capability URL vazada pode reutilizar a mesma mídia durante TTL |
| Command injection | injetar flags/headers/URL no FFmpeg | `create_subprocess_exec`; sem shell; protocolo allowlist; URL/header allowlist e CRLF filtering | zero-day do FFmpeg/parser de mídia |
| XSS | título/erro remoto virar HTML executável | frontend usa `textContent`; CSP `script-src 'self'`; thumbnails allowlist | bug futuro que introduza `innerHTML`/template inseguro |
| Host/CORS/CSRF abuse | Host poisoning, cross-site API calls | TrustedHost; sem CORS aberto; browser cross-site API request recusado | clientes não-browser podem chamar API, por design |
| Rate abuse | muitas resoluções/Range/jobs | rate limit por cliente, limites globais e por cliente, bounded sessions | botnet/muitos IPs requer edge rate limit |
| Slow-read DoS | cliente lê bytes lentamente e prende slot | timeout por chunk de resposta + limites de streams ativos | proxy/edge também deve possuir limites apropriados |
| Origem travada | CDN mantém conexão sem enviar bytes | timeout de leitura upstream | indisponibilidade temporária da origem |
| CPU/FFmpeg exhaustion | MP3/merge repetido | slots globais, 1 job por cliente, timeout FFmpeg, MP3 1 thread, limites de CPU/memória/PIDs do container | abuso distribuído ainda exige edge/WAF |
| RAM/session exhaustion | criar sessões/formats sem parar | TTL, máximo de sessões/candidatos, body limit | múltiplas instâncias precisam store/limiter compartilhado |
| Supply-chain | pacote/action/image malicioso ou atualização silenciosa | locks/hashes/digests, ignore-scripts, scanners, CodeQL/Trivy | atualização aprovada sem revisão humana |
| Secret leakage | logs capturam URLs assinadas/capabilities | Uvicorn access log desligado; erros externos genéricos; FFmpeg stderr não retorna ao cliente | proxy reverso pode registrar paths se access log estiver ativo |
| Persistent frontend compromise | service worker malicioso persiste após rollback | service worker removido; sem offline executable cache | cache normal do navegador/CDN deve respeitar política de deploy |

## Hardening do container

O perfil de referência deve continuar:

- usuário não-root;
- filesystem read-only;
- `cap_drop: ALL`;
- `no-new-privileges`;
- seccomp padrão do runtime;
- PID, CPU, memória e file descriptors limitados;
- `/tmp` limitado, `noexec,nosuid,nodev`;
- sem Docker socket;
- sem volume do host;
- sem secrets/cookies do YouTube no container público;
- somente proxy reverso exposto à Internet.

## Regras para autenticação e pagamentos futuros

Nenhum login/pagamento deve ser adicionado ao MVP atual sem uma nova revisão. Antes disso:

1. modelo de identidade e tenant explícito;
2. autorização central server-side;
3. cookies `Secure`, `HttpOnly`, `SameSite` apropriado, se cookies forem usados;
4. CSRF quando houver credenciais baseadas em cookie;
5. sessão revogável e rotação de tokens;
6. nenhum token sensível em URL, localStorage, analytics ou logs;
7. webhooks de pagamento com assinatura verificada e proteção contra replay;
8. idempotência em operações financeiras;
9. RLS/testes de acesso cruzado para todo dado multi-tenant;
10. trilha de auditoria para mudança de plano/permissão;
11. rate limit compartilhado (Redis/edge) antes de múltiplos workers/instâncias.

## Configuração obrigatória de produção

- `WEB_ALLOWED_HOSTS` deve conter somente o hostname real;
- `WEB_TRUSTED_PROXY_CIDRS` deve conter somente a rede exata do proxy; nunca `0.0.0.0/0`;
- HTTPS obrigatório;
- HSTS apenas depois de HTTPS validado;
- Swagger/OpenAPI desligados;
- access logs do proxy devem ser desligados ou redigir paths com capability tokens;
- edge rate limit/bot protection obrigatório para exposição ampla;
- branch ruleset deve exigir PR, checks e revisão de CODEOWNERS;
- ambientes de staging e produção devem possuir credenciais/segredos distintos;
- nenhuma chave administrativa do provedor de cloud/banco deve chegar ao frontend.

## Riscos residuais aceitos no staging

- FFmpeg, yt-dlp e parsers processam dados externos e podem sofrer zero-days;
- limiter interno é por processo;
- capability tokens ficam em paths por até o TTL da sessão;
- direct-first revela ao navegador o redirect assinado do CDN por design;
- uma botnet pode distribuir abuso entre muitos IPs;
- sem autenticação, o serviço é deliberadamente público dentro dos limites configurados.

Por isso staging deve começar restrito (Access/VPN) e ser observado antes de abertura ampla.
