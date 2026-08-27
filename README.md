# YouTube Downloader

Aplicação desktop de uso pessoal para organizar downloads de mídia do YouTube com **PySide6, yt-dlp e FFmpeg**.

> Projeto em evolução. A edição pública foi refatorada para remover dados pessoais, endurecer defaults e manter uma interface coerente com o mockup de portfólio. Use apenas com conteúdo que você tem direito de acessar e respeite os termos da plataforma.

## O que está implementado

- interface desktop em **PySide6 / Qt 6**;
- navegação real entre **Fila, Histórico, Listas TXT e Configurações**;
- fila visual com progresso, velocidade, conclusão, erro e cancelamento;
- downloads MP3 e MP4;
- seleção de qualidade;
- recorte por intervalo de tempo;
- pesquisa por texto e resolução de links;
- expansão de playlists;
- importação de listas TXT com **pré-visualização e validação antes da fila**;
- monitor de clipboard **opt-in**;
- concorrência configurável por slider;
- histórico local persistente de concluídos, erros e cancelamentos;
- preferências persistidas em diretório XDG do usuário;
- retomada/retries e downloads fragmentados pelo `yt-dlp`;
- CI com testes offline, testes da navegação e smoke test da GUI em modo offscreen.

## Interface

A GUI usa fundo quase preto, cards grafite, acento vermelho e navegação lateral. A sidebar não é decorativa: cada item abre uma área funcional da aplicação.

### Fila

Entrada de link/pesquisa, monitor de clipboard, fila de jobs e configuração rápida de formato, qualidade, recorte, pasta e concorrência.

### Histórico

Registra localmente downloads concluídos, cancelados e falhas. É possível abrir a pasta de destino e limpar os registros sem apagar as mídias baixadas.

### Listas TXT

Permite escolher um arquivo, revisar até 500 entradas, identificar itens válidos/inválidos e somente depois enviar os válidos para processamento.

### Configurações

Centraliza pasta padrão, formato, qualidade de áudio/vídeo, concorrência, comportamento do clipboard e informações do ambiente local.

## Arquitetura

```text
PySide6 GUI
   │
   ├── QStackedWidget
   │   ├── Fila
   │   ├── Histórico
   │   ├── Listas TXT
   │   └── Configurações
   │
   ├── entrada / clipboard / TXT
   │          │
   │          ▼
   │      resolver.py
   │          │
   └──────► fila de jobs ──► QThreadPool
                               │
                               ▼
                         downloader.py
                               │
                        yt-dlp + FFmpeg

Persistência local
   ├── config.json
   └── history.json
```

Trabalho de rede e download ocorre fora da thread principal para evitar congelar a interface.

## Melhorias aplicadas na edição pública

- substituição da GUI legada em CustomTkinter por PySide6;
- navegação exclusiva com `QButtonGroup` + `QStackedWidget`;
- remoção de placeholders de navegação sem comportamento;
- remoção de lista pessoal que havia sido versionada;
- URLs externas ao YouTube não são aceitas silenciosamente;
- verificação TLS não é desativada;
- `ignoreerrors` deixou de mascarar falhas;
- retries e fragment retries explícitos;
- concorrência de fragmentos para melhorar throughput quando suportado;
- configuração e histórico salvos de forma atômica;
- limite visual de concorrência entre 1 e 8 jobs;
- validação de recortes antes de iniciar o download;
- nomes de saída incluem o ID do vídeo para reduzir colisões;
- instalação e execução não dependem da ativação manual do virtualenv;
- testes para classificação de entrada, recorte, configuração, histórico, navegação e opções de segurança.

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

Quando o repositório estiver público, HTTPS funciona sem autenticação:

```bash
git clone https://github.com/Jczarf/public-youtube-downloader.git
```

Os scripts usam diretamente `.venv/bin/python`; **não é necessário ativar o ambiente virtual**.

Para escolher explicitamente o interpretador:

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

Ou sem ativar o virtualenv:

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

A aplicação usa o diretório XDG de configuração:

```text
$XDG_CONFIG_HOME/youtube-downloader/
```

ou, por padrão:

```text
~/.config/youtube-downloader/
```

Arquivos principais:

```text
config.json   # preferências
history.json  # histórico local limitado
```

Arquivos baixados, logs, listas pessoais, ambientes virtuais e temporários permanecem fora do Git.

## Testes

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

O GitHub Actions também compila o projeto, valida scripts, executa verificações de publicação e instancia a GUI com `QT_QPA_PLATFORM=offscreen`.

## Limitações

- compatibilidade com o YouTube depende do `yt-dlp` e pode mudar quando a plataforma muda;
- FFmpeg é necessário para conversão, merge e recortes;
- o downloader de vídeo limita explicitamente as opções de qualidade a 480p, 720p e 1080p nesta edição;
- a baseline principal do CI usa Python 3.12;
- CI headless não substitui inspeção visual em um desktop Linux real;
- histórico registra metadados operacionais locais, não o conteúdo dos arquivos baixados.

## Status

**Projeto pessoal em evolução / aplicação funcional para uso local.**

## Autor

**Júlio Cézar** — estudante de Ciência da Computação e Técnico em Desenvolvimento de Sistemas.
