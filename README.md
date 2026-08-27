# YouTube Downloader

Aplicação desktop de uso pessoal para organizar downloads de mídia do YouTube com **PySide6, yt-dlp e FFmpeg**.

> Projeto em evolução. A edição pública foi refatorada para remover dados pessoais, endurecer defaults e aproximar a interface do mockup de portfólio. Use apenas com conteúdo que você tem direito de acessar e respeite os termos da plataforma.

## O que está implementado

- interface desktop em **PySide6 / Qt 6**;
- fila visual com progresso, velocidade, conclusão, erro e cancelamento;
- downloads MP3 e MP4;
- seleção de qualidade;
- recorte por intervalo de tempo;
- pesquisa por texto e resolução de links;
- expansão de playlists;
- importação de listas TXT;
- monitor de clipboard **opt-in**;
- concorrência configurável;
- preferências persistidas em diretório XDG do usuário;
- retomada/retries e downloads fragmentados pelo `yt-dlp`;
- CI com testes offline e smoke test da GUI em modo offscreen.

## Direção visual

A GUI usa o mesmo estilo do mockup definido para o portfólio: fundo quase preto, cards grafite, acento vermelho, navegação lateral, fila central e configuração rápida à direita.

A interface não simula recursos inexistentes. A fila e os controles principais são funcionais; páginas secundárias da navegação ainda estão sendo ampliadas gradualmente.

## Arquitetura

```text
PySide6 GUI
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
```

O trabalho de rede e download sai da thread principal para não congelar a interface.

## Melhorias aplicadas na edição pública

- substituição da GUI legada em CustomTkinter por PySide6;
- remoção de lista pessoal que havia sido versionada;
- URLs externas ao YouTube não são aceitas silenciosamente;
- verificação TLS não é desativada;
- `ignoreerrors` deixou de mascarar falhas;
- retries e fragment retries explícitos;
- concorrência de fragmentos para melhorar throughput quando suportado;
- configuração salva de forma atômica;
- limite visual de concorrência entre 1 e 8 jobs;
- validação de recortes antes de iniciar o download;
- nomes de saída incluem o ID do vídeo para reduzir colisões;
- instalação e execução não dependem da ativação manual do virtualenv;
- testes para classificação de entrada, recorte, configuração e opções de segurança.

## Instalação

### Requisitos

- **Python 3.12 recomendado e usado como baseline principal do CI**;
- Python 3.11+ pode funcionar, mas versões diferentes de 3.12 não são a baseline principal de validação;
- FFmpeg instalado no sistema.

### Caminho recomendado — funciona em Bash, Zsh e Fish

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

Se quiser escolher explicitamente o interpretador durante a instalação:

```bash
PYTHON_BIN=python3.12 ./install.sh
```

### Instalação manual

Crie o ambiente:

```bash
python3 -m venv .venv
```

A ativação depende do shell.

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

### Alternativa independente do shell

Você também pode ignorar completamente a ativação:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

### Instalar FFmpeg

Ubuntu / Debian:

```bash
sudo apt install ffmpeg
```

Arch Linux / CachyOS:

```bash
sudo pacman -S ffmpeg
```

## Dados locais

As preferências ficam em:

```text
$XDG_CONFIG_HOME/youtube-downloader/config.json
```

ou, quando `XDG_CONFIG_HOME` não está definido:

```text
~/.config/youtube-downloader/config.json
```

Arquivos baixados, bancos, logs, listas pessoais e arquivos temporários permanecem fora do Git.

## Testes

Com o virtualenv criado:

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

O workflow do GitHub Actions também compila o projeto e instancia a GUI com `QT_QPA_PLATFORM=offscreen`.

## Limitações

- compatibilidade com o YouTube depende do `yt-dlp` e pode mudar quando a plataforma muda;
- FFmpeg é necessário para conversão, merge e recortes;
- a baseline principal do CI usa Python 3.12; outras versões devem ser tratadas como compatibilidade a confirmar;
- o CI headless não substitui inspeção visual em Linux desktop real;
- Histórico e páginas secundárias da navegação ainda estão em evolução.

## Status

**Projeto pessoal em evolução / aplicação funcional para uso local.**

## Autor

**Júlio Cézar** — estudante de Ciência da Computação e Técnico em Desenvolvimento de Sistemas.
