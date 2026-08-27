# YouTube Downloader

Aplicação desktop de uso pessoal para organizar downloads de mídia do YouTube com **PySide6, yt-dlp e FFmpeg**.

> Projeto em evolução. A edição pública foi refatorada para remover dados pessoais, endurecer defaults, melhorar concorrência e transformar a interface em uma aplicação desktop coerente com o mockup de portfólio. Use apenas com conteúdo que você tem direito de acessar e respeite os termos da plataforma.

## O que está implementado

- interface desktop em **PySide6 / Qt 6**;
- navegação real e exclusiva entre **Fila**, **Histórico** e **Listas TXT**;
- fila visual com progresso, velocidade, conclusão, erro e cancelamento;
- cancelamento também para jobs que ainda aguardam uma thread de download;
- downloads MP3 e MP4;
- seletor de qualidade adequado ao formato;
- recorte por intervalo de tempo;
- pesquisa por texto e resolução de links;
- expansão de playlists;
- importação e pré-visualização de listas TXT antes de enfileirar;
- monitor de clipboard **opt-in** e persistido localmente;
- concorrência configurável por slider;
- pools separados para resolução de links e downloads;
- histórico local de concluídos, erros e cancelamentos;
- preferências persistidas em diretório XDG;
- retomada/retries e downloads fragmentados pelo `yt-dlp`;
- CI com testes offline e smoke test da GUI em modo offscreen;
- auditoria de segurança separada para a edição pública.

## UX da aplicação

A interface segue uma estrutura enxuta:

```text
YouTube Downloader
│
├── Fila
│   ├── adicionar link ou pesquisa
│   ├── monitor de clipboard
│   ├── fila de downloads
│   └── configuração rápida
│
├── Histórico
│   ├── concluídos
│   ├── erros e cancelamentos
│   ├── abrir pasta
│   └── limpar registros locais
│
└── Listas TXT
    ├── escolher arquivo
    ├── validar entradas
    ├── pré-visualizar
    └── adicionar válidos à fila
```

Não existe uma página separada de configurações: pasta, formato, qualidade, recorte e concorrência já ficam disponíveis no painel **Configuração rápida**, evitando duplicação de controles e caminhos desnecessários.

## Direção visual

A GUI reproduz o estilo definido para o portfólio:

- shell escuro com borda externa arredondada;
- sidebar grafite;
- cards com bordas suaves;
- vermelho como cor de ação e seleção;
- verde para estados positivos;
- azul para informação de ambiente;
- seletor de qualidade estilizado;
- recorte agrupado em um único card;
- seletor compacto de pasta;
- slider visual de concorrência;
- estados vazios próprios em vez de widgets com aparência nativa clara.

A intenção é manter uma aparência de produto desktop sem esconder o estado real do projeto: somente controles com comportamento implementado permanecem expostos.

## Arquitetura

```text
PySide6 GUI
   │
   ├── entrada / clipboard / TXT
   │          │
   │          ▼
   │    pool de resolução
   │          │
   │      resolver.py
   │          │
   └──────► fila de jobs ──► pool de downloads
                               │
                               ▼
                         downloader.py
                               │
                        yt-dlp + FFmpeg

Histórico / preferências
          │
          ▼
      JSON local XDG
```

Resolução de pesquisas e playlists não ocupa as vagas configuradas para downloads. Isso evita que tarefas de metadados reduzam artificialmente a concorrência das transferências.

## Melhorias aplicadas na edição pública

- substituição da GUI legada em CustomTkinter por PySide6;
- remoção de lista pessoal que havia sido versionada;
- remoção de navegação decorativa/placeholder;
- eliminação da página redundante de configurações;
- URLs externas ao YouTube não são aceitas silenciosamente;
- validação TLS não é desativada;
- `ignoreerrors` não mascara falhas;
- retries e fragment retries explícitos;
- concorrência de fragmentos quando suportada pelo `yt-dlp`;
- configuração salva de forma atômica;
- histórico salvo de forma atômica;
- cancelamento de jobs pendentes e em execução;
- pools separados para metadados e downloads;
- limite de concorrência entre 1 e 8 jobs;
- validação de recortes antes de iniciar o download;
- nomes de saída incluem o ID do vídeo para reduzir colisões;
- instalação e execução não dependem da ativação manual do virtualenv;
- monitor de clipboard desligado por padrão;
- testes de classificação, recorte, persistência, navegação e controles principais.

## Instalação

### Requisitos

- **Python 3.12 recomendado e usado como baseline principal do CI**;
- Python 3.11+ pode funcionar, mas versões diferentes de 3.12 não são a baseline principal de validação;
- FFmpeg instalado no sistema.

### Caminho recomendado — Bash, Zsh e Fish

Enquanto o repositório estiver privado, use SSH se sua chave GitHub já estiver configurada:

```bash
git clone git@github.com:Jczarf/public-youtube-downloader.git
cd public-youtube-downloader
./install.sh
./run.sh
```

Quando o repositório estiver público, HTTPS também funciona sem autenticação:

```bash
git clone https://github.com/Jczarf/public-youtube-downloader.git
```

Os scripts usam diretamente `.venv/bin/python`, portanto **não é necessário ativar o ambiente virtual**.

Se quiser escolher explicitamente o interpretador:

```bash
PYTHON_BIN=python3.12 ./install.sh
```

### Instalação manual

```bash
python3 -m venv .venv
```

**Bash / Zsh:**

```bash
source .venv/bin/activate
```

**Fish:**

```fish
source .venv/bin/activate.fish
```

Depois:

```bash
python -m pip install -r requirements.txt
python main.py
```

### Sem ativar o virtualenv

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
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

Arquivos baixados, listas pessoais, bancos, logs e temporários permanecem fora do Git.

## Testes

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

O GitHub Actions também compila o projeto e instancia a GUI com `QT_QPA_PLATFORM=offscreen`.

## Segurança e privacidade

- clipboard desligado por padrão;
- nenhum link é lido até ativação explícita;
- TLS do `yt-dlp` não é desativado;
- URLs externas ao YouTube são rejeitadas;
- arquivos pessoais e downloads ficam fora do repositório;
- preferências e histórico são locais;
- scanner dedicado verifica a edição pública no CI.

Veja também [`SECURITY.md`](SECURITY.md).

## Limitações

- compatibilidade com o YouTube depende do `yt-dlp` e pode mudar quando a plataforma muda;
- FFmpeg é necessário para conversão, merge e recortes;
- a baseline principal do CI usa Python 3.12;
- o CI headless não substitui inspeção visual em Linux desktop real;
- a qualidade visual pode variar ligeiramente conforme fonte, compositor, escala e tema do desktop;
- o projeto é uma ferramenta pessoal em evolução, não um produto comercial ou serviço de download.

## Status

**Projeto pessoal em evolução / aplicação funcional para uso local.**

## Autor

**Júlio Cézar** — estudante de Ciência da Computação e Técnico em Desenvolvimento de Sistemas.
