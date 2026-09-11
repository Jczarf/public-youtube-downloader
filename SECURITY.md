# Segurança

Este repositório possui dois modos independentes:

- **desktop local**, baseado em PySide6;
- **web/PWA**, baseado em FastAPI, yt-dlp, Deno, HTTPX e FFmpeg.

A aplicação web deve ser tratada como um serviço exposto a entrada não confiável. Um link válido do YouTube e a própria mídia hospedada no YouTube continuam sendo conteúdo controlável por terceiros.

## Threat model da aplicação web

As principais classes de abuso consideradas são:

1. **SSRF / open proxy**
   - tentativa de fazer a VPS acessar localhost, metadata services, rede privada ou hosts arbitrários;
   - redirects de origem para destinos não autorizados;
   - abuso do FFmpeg como cliente de protocolos arbitrários.

2. **negação de serviço / consumo irrestrito**
   - muitas resoluções yt-dlp;
   - muitas conexões Range;
   - jobs longos de FFmpeg;
   - vídeos excessivamente longos ou grandes;
   - criação de milhares de sessões para consumir RAM;
   - conexões abertas aguardando slots.

3. **injeção e execução externa**
   - headers com CR/LF;
   - opções/URLs repassadas para FFmpeg;
   - nomes de arquivo e títulos remotos;
   - conteúdo de mídia malformado explorando parsers.

4. **supply chain**
   - dependências Python/Node vulneráveis;
   - mudança silenciosa de dependências transitivas;
   - GitHub Actions mutáveis;
   - imagens Docker e pacotes do sistema vulneráveis.

5. **configuração insegura**
   - Host header arbitrário;
   - confiança cega em X-Forwarded-For;
   - documentação OpenAPI exposta desnecessariamente;
   - ausência de CSP/HSTS/anti-frame;
   - container com privilégios excessivos;
   - domínio público aberto antes das proteções de edge.

6. **vazamento de capability tokens**
   - os IDs efêmeros de sessão presentes nas rotas de stream funcionam como capabilities;
   - logs de acesso não devem armazenar esses caminhos em produção.

## Controles implementados

### Entrada e SSRF

- a API web aceita somente links diretos do YouTube reconhecidos pelo parser;
- o link de entrada é canonicalizado antes da extração;
- streams do servidor aceitam somente HTTPS em `googlevideo.com` ou subdomínios;
- URLs com credenciais embutidas ou porta diferente de 443 são recusadas;
- thumbnails aceitas pelo frontend são limitadas a HTTPS em `ytimg.com`;
- redirects HTTP não são seguidos automaticamente;
- cada redirect é revalidado e limitado;
- nenhum endpoint recebe do cliente uma URL arbitrária para proxy;
- headers enviados à origem usam allowlist positiva;
- Cookie, Authorization, Host, X-Forwarded-* e headers arbitrários não são repassados;
- FFmpeg usa allowlist de protocolos e recebe apenas URLs previamente validadas.

### Recursos e DoS

Os defaults de staging são intencionalmente conservadores:

- sessões efêmeras: 10 minutos;
- máximo de sessões em memória: 256;
- máximo de candidatos por sessão: 64;
- máximo de duração: 7200 s;
- máximo conhecido por stream: 1 GiB;
- resolução yt-dlp simultânea global: 4;
- relay simultâneo global: 8;
- FFmpeg simultâneo global: 2;
- resolução ativa por cliente: 1;
- processamento FFmpeg ativo por cliente: 1;
- relay ativo por cliente: 6;
- rate limiting por cliente em rotas públicas;
- FFmpeg possui timeout de wall clock;
- admissão de FFmpeg é fail-fast: requisições não ficam formando fila ilimitada.

Todos os limites relevantes podem ser reduzidos por variável de ambiente.

### Aplicação HTTP

- `TrustedHostMiddleware`;
- OpenAPI, Swagger e ReDoc desabilitados por padrão;
- CSP restritiva;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- Permissions Policy restritiva;
- Cross-Origin-Opener-Policy;
- HSTS opcional e recomendado somente atrás de HTTPS corretamente configurado;
- API e respostas de mídia usam `Cache-Control: no-store`;
- não existe CORS aberto;
- `X-Forwarded-For` é ignorado por padrão e só é usado quando o peer imediato pertence a uma rede explicitamente confiável;
- erros externos são reduzidos a mensagens genéricas e não devolvem stderr do FFmpeg nem exceções completas do yt-dlp.

### FFmpeg

- subprocesso criado sem shell;
- usuário não root;
- headers sanitizados;
- protocolos restritos;
- timeout de leitura/remoto;
- timeout global de processamento;
- MP3 limitado a uma thread;
- stderr remoto não é devolvido ao cliente;
- merge de vídeo usa stream copy quando possível.

### Container

A configuração de referência usa:

- usuário não root;
- filesystem somente leitura;
- `cap_drop: ALL`;
- `no-new-privileges`;
- limite de PIDs;
- limite de CPU e memória;
- `tmpfs` limitado;
- porta publicada somente em loopback no compose local;
- healthcheck;
- sem volume persistente para downloads.

O runtime padrão do Docker continua fornecendo seccomp. Em produção, o proxy reverso é o único componente que deve expor a aplicação à Internet.

### Supply chain e CI

- versões diretas Python fixadas;
- grafo frontend versionado em `package-lock.json`;
- instalações Node usam `npm ci`;
- scripts de instalação npm são desabilitados;
- GitHub Actions de terceiros são referenciadas por commit SHA;
- permissões de Actions são somente leitura;
- credenciais do checkout não permanecem no repositório;
- `pip-audit`;
- `npm audit`;
- scanner de secrets na árvore e histórico alcançável;
- build real do container;
- Trivy na imagem final para vulnerabilidades CRITICAL/HIGH corrigíveis;
- Trivy na configuração Docker;
- smoke test da imagem construída.

## Configuração obrigatória antes de exposição pública

Antes de usar um domínio público:

1. defina `WEB_ALLOWED_HOSTS` para o hostname real;
2. habilite HTTPS no proxy;
3. somente depois habilite `WEB_ENABLE_HSTS=1`;
4. mantenha `WEB_ENABLE_DOCS=0`;
5. configure `WEB_TRUSTED_PROXY_CIDRS` apenas para a sub-rede exata do proxy se for necessário obter o IP real;
6. adicione rate limiting/bot protection no edge (Cloudflare ou equivalente);
7. para staging, prefira Cloudflare Access, VPN ou outra camada de acesso restrito;
8. não monte Docker socket, diretórios do host ou segredos desnecessários no container;
9. não adicione cookies do YouTube ao serviço público sem uma revisão separada de risco.

## Riscos residuais conhecidos

Nenhum serviço exposto é “invulnerável”. Permanecem riscos que exigem defesa operacional:

- FFmpeg e yt-dlp processam dados externos e podem receber futuras vulnerabilidades;
- o rate limiting interno é por processo, portanto escala horizontal exige um limitador compartilhado ou edge/WAF;
- IP real atrás de proxy depende de configuração correta da cadeia de confiança;
- uma conta/botnet com muitos IPs ainda pode produzir carga distribuída;
- URLs assinadas do CDN existem temporariamente na RAM do processo;
- o modo direct-first entrega ao navegador um redirect temporário do CDN;
- um exploit zero-day no parser de mídia ainda pode alcançar o processo do container, motivo pelo qual o isolamento do container e a atualização de pacotes continuam necessários.

## Relato de vulnerabilidades

Não publique chaves, cookies, URLs assinadas, dumps, tokens de sessão ou detalhes exploráveis em issue pública.

Ao relatar uma vulnerabilidade, inclua de forma privada:

- versão/commit afetado;
- endpoint ou componente;
- impacto;
- passos mínimos de reprodução;
- se houve acesso a dados ou apenas demonstração controlada.

Não execute testes destrutivos, DoS ou acesso a sistemas de terceiros sem autorização.
