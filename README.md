# YouTube Downloader

Aplicação desktop de uso pessoal para organizar downloads de mídia do YouTube com **PySide6, yt-dlp e FFmpeg**.

> Projeto pessoal em evolução. A edição pública foi refatorada para remover dados pessoais, reduzir superfície de ataque, melhorar concorrência e oferecer uma interface desktop consistente com o mockup de portfólio. Use apenas com conteúdo que você tem direito de acessar e respeite os termos da plataforma.

## O que está implementado

- interface desktop em **PySide6 / Qt 6**;
- navegação real e exclusiva entre **Fila**, **Histórico** e **Listas TXT**;
- fila visual com estados separados de aguardando, baixando, concluído, cancelado e erro;
- downloads MP3 e MP4;
- seletor de qualidade por formato;
- recorte por intervalo de tempo;
- pesquisa por texto;
- expansão de playlists com limite de itens;
- detecção de vídeo aberto dentro de playlist, com escolha explícita entre **somente este vídeo** e **playlist completa**;
- importação e pré-visualização de TXT antes de enfileirar;
- monitor de clipboard **opt-in e somente da sessão**;
- concorrência configurável por slider;
- pools separados para resolução e downloads;
- histórico local de concluídos, erros e cancelamentos;
- preferências locais em diretório XDG;
- retries, retomada e fragmentos concorrentes do `yt-dlp`;
- estados vazios próprios, sem scrollbars decorativas;
- diálogos próprios no tema escuro;
- CI com testes offline e smoke test da GUI;
- auditoria automática de segredos e vulnerabilidades conhecidas de dependências.

## Execução e privacidade

O aplicativo roda **localmente**. Ele não possui backend próprio, servidor web, API exposta ou porta de rede aberta.

```text
PySide6 GUI local
      │
      ├── configuração / histórico ──► JSON local XDG
      │
      ├── resolução ─────────────────► yt-dlp ─► YouTube
      │
      └── downloads ─────────────────► yt-dlp + FFmpeg
```

A aplicação precisa de internet para pesquisa/download e acessa o YouTube/CDNs por conexões de saída. FFmpeg executa localmente.

O clipboard começa **desligado em toda nova execução**. Mesmo que tenha sido ativado anteriormente, ele não é reativado automaticamente no próximo start.

## UX

```text
YouTube Downloader
│
├── Fila
│   ├── link ou pesquisa
│   ├── clipboard opt-in
│   ├── fila de downloads
│   └── configuração rápida
│
├── Histórico
│   ├── concluídos
│   ├── erros e cancelamentos
│   ├── abrir pasta
│   └── limpar registros
│
└── Listas TXT
    ├── escolher arquivo
    ├── validar entradas
    ├── pré-visualizar
    └── adicionar válidos à fila
```

Quando um link de vídeo contém também um parâmetro `list=`, o aplicativo não presume que o usuário queira baixar dezenas de itens. Ele exibe um diálogo próprio com três opções:

```text
Vídeo dentro de playlist
├── Somente este vídeo   ← opção segura/padrão
├── Playlist completa
└── Cancelar
```

A mesma decisão é preservada para links detectados pelo monitor de clipboard. Em importações TXT, um link explícito `/playlist?list=...` continua sendo a forma indicada para solicitar uma playlist inteira em lote.

Não existe uma página separada de configurações: pasta, formato, qualidade, recorte e concorrência ficam no painel **Configuração rápida**.

## Direção visual

A GUI usa shell escuro com borda externa arredondada, sidebar grafite, cards de baixo contraste, vermelho como cor de ação, verde para sucesso e azul para informação. Estados vazios, diálogos e feedback foram desenhados no próprio tema para não depender da aparência nativa clara do sistema.

Textos vindos da rede, como títulos e mensagens de erro, são exibidos como **texto simples**, evitando interpretação de HTML na interface.

## Hardening aplicado

- URLs externas ao YouTube são rejeitadas;
- dentro do YouTube, somente rotas reconhecidas de vídeo, playlist e pesquisa são aceitas;
- links HTTP válidos são canonicalizados para HTTPS;
- links de vídeo com `list=` preservam contexto até a escolha do usuário, sem disparar playlist inteira silenciosamente;
- rotas de redirecionamento, canais e páginas genéricas não são tratadas como vídeo;
- TLS não é desativado;
- FFmpeg ausente bloqueia downloads antes de consumir tempo/rede;
- configuração inválida é normalizada para defaults seguros;
- pasta de destino precisa ser absoluta (ou `~`) e a raiz `/` é recusada;
- config/histórico usam escrita atômica e permissões privadas em sistemas POSIX;
- histórico não salva URL do vídeo e redige URLs de mensagens de erro;
- TXT: máximo de **2 MB**, **500 entradas** e **4096 caracteres por linha**;
- playlists são iteradas até o limite em vez de materializar toda a coleção;
- o downloader evita uma extração duplicada de metadados antes da transferência;
- MP4 prioriza vídeo MP4 + áudio M4A quando disponíveis;
- scripts `install.sh` e `run.sh` funcionam mesmo quando chamados a partir de outro diretório;
- dependências de runtime são fixadas na baseline validada;
- Security Audit executa scanner de segredos e `pip-audit`.

## Instalação

### Requisitos

- **Python 3.12** recomendado e usado no CI;
- Python 3.11+ pode funcionar, mas 3.12 é a baseline de referência;
- FFmpeg instalado no sistema.

Enquanto o repositório estiver privado, use SSH se sua chave GitHub estiver configurada:

```bash
git clone git@github.com:Jczarf/public-youtube-downloader.git
cd public-youtube-downloader
./install.sh
./run.sh
```

Os scripts usam diretamente `.venv/bin/python`; não é necessário ativar o ambiente virtual. Eles também resolvem o diretório do projeto automaticamente, portanto podem ser chamados por caminho absoluto.

Para escolher o interpretador:

```bash
PYTHON_BIN=python3.12 ./install.sh
```

### Instalação manual

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

No Fish, se quiser ativar o ambiente:

```fish
source .venv/bin/activate.fish
```

### FFmpeg

Ubuntu / Debian:

```bash
sudo apt install ffmpeg
```

Arch Linux / CachyOS:

```bash
sudo pacman -S ffmpeg
```

Sem FFmpeg o aplicativo abre, mas bloqueia o início de downloads e informa o requisito.

## Dados locais

Preferências:

```text
$XDG_CONFIG_HOME/youtube-downloader/config.json
```

ou:

```text
~/.config/youtube-downloader/config.json
```

Histórico:

```text
~/.config/youtube-downloader/history.json
```

Em sistemas POSIX, os arquivos são gravados com permissão `0600` e o diretório privado usa `0700` quando o sistema de arquivos suporta essa semântica.

O histórico guarda somente dados necessários para a UX: título, estado, formato, pasta, mensagem sanitizada e data. A URL original do vídeo não é persistida.

## Dependências validadas

```text
PySide6==6.11.2
yt-dlp==2026.8.19
```

As versões são fixadas para que uma instalação reproduza a mesma baseline testada. Atualizações devem ser feitas conscientemente e acompanhadas de nova execução de CI + Security Audit.

## Testes

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

O CI também executa `pip check`, compila o código e instancia a GUI com `QT_QPA_PLATFORM=offscreen`.

Os testes cobrem também a detecção de `watch?v=...&list=...`, a escolha de vídeo/playlist e o cancelamento da decisão antes de iniciar a resolução.

O workflow **Security Audit** verifica possíveis segredos na árvore/histórico Git alcançável e vulnerabilidades conhecidas das dependências Python via `pip-audit`.

## Limitações

- mudanças do YouTube podem exigir atualização do `yt-dlp`;
- FFmpeg é obrigatório para os fluxos suportados;
- cancelamento é cooperativo e pode não ser instantâneo durante resolução de metadados ou processamento externo;
- CI headless não substitui inspeção visual em um desktop Linux real;
- aparência pode variar levemente conforme fonte, compositor, escala e tema;
- não é um serviço comercial nem um backend de download.

Veja também [`SECURITY.md`](SECURITY.md).

## Status

**Aplicação funcional para uso local / projeto pessoal em evolução.**

## Autor

**Júlio Cézar** — estudante de Ciência da Computação e Técnico em Desenvolvimento de Sistemas.
