<div align="center">

# YouTube Downloader

Aplicação desktop para **baixar, organizar e acompanhar mídias do YouTube** com interface gráfica, fila assíncrona e processamento local.

[![CI](https://github.com/Jczarf/public-youtube-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Jczarf/public-youtube-downloader/actions/workflows/ci.yml)
[![Security Audit](https://github.com/Jczarf/public-youtube-downloader/actions/workflows/security-audit.yml/badge.svg)](https://github.com/Jczarf/public-youtube-downloader/actions/workflows/security-audit.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/PySide6-Qt%206-41CD52?logo=qt&logoColor=white)
![yt-dlp](https://img.shields.io/badge/yt--dlp-2026.8.19-FF0000?logo=youtube&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?logo=ffmpeg&logoColor=white)

</div>

> Projeto pessoal em evolução. Use somente com conteúdo que você tem direito de acessar e respeite os termos da plataforma. O aplicativo roda localmente e não envia sua fila, histórico ou configurações para um backend próprio.

## Interface

A GUI foi construída com **PySide6 / Qt 6** e concentra entrada de links, pesquisa, fila, histórico, listas TXT e configuração rápida em uma única aplicação desktop.

<p align="center">
  <img src="https://raw.githubusercontent.com/Jczarf/Jczarf/main/assets/youtube-downloader-ui.webp" alt="Interface do YouTube Downloader" width="100%" />
</p>

<details>
<summary><strong>Ver resultado de uma sessão real</strong></summary>
<br />
<p align="center">
  <img src="https://raw.githubusercontent.com/Jczarf/Jczarf/main/assets/youtube-downloader-output.webp" alt="YouTube Downloader e arquivos gerados" width="100%" />
</p>
</details>

## Visão geral

| Área | Implementação |
| --- | --- |
| Interface | PySide6 / Qt 6, tema escuro e navegação entre Fila, Histórico e Listas TXT |
| Download | `yt-dlp`, MP3/MP4, qualidade configurável, recorte e playlists |
| Processamento | FFmpeg local para os fluxos de áudio e vídeo suportados |
| Concorrência | pools separados para resolução e download, com limite configurável |
| Organização | histórico local, filas visuais e importação de listas TXT |
| Privacidade | configurações e histórico locais em diretório XDG |
| Qualidade | pytest, compile check, smoke test da GUI, scanner de segredos e `pip-audit` |

## Funcionalidades

- downloads em **MP3 e MP4**;
- seletor de qualidade por formato;
- recorte por intervalo de tempo;
- pesquisa por texto;
- expansão de playlists com limite de itens;
- detecção de vídeo aberto dentro de playlist, com escolha entre **somente este vídeo** e **playlist completa**;
- fila visual com estados de aguardando, baixando, concluído, cancelado e erro;
- importação e pré-visualização de arquivos TXT antes de enfileirar;
- monitor de clipboard **opt-in e somente da sessão**;
- concorrência configurável;
- histórico local de concluídos, erros e cancelamentos;
- retries com backoff e retomada;
- autenticação por cookies do navegador somente quando ativada explicitamente;
- estados vazios e diálogos integrados ao tema da aplicação.

## Como funciona

```text
PySide6 GUI
      │
      ├── configuração / histórico ──► JSON local XDG
      │
      ├── resolução ─────────────────► yt-dlp ─► YouTube
      │
      └── downloads ─────────────────► yt-dlp + FFmpeg
```

A interface não executa rede nem processamento pesado diretamente na thread principal. Resolução e download usam workers separados para manter a GUI responsiva durante operações longas.

O aplicativo não possui backend próprio, servidor web, API exposta ou porta de rede aberta. Ele usa conexões de saída para YouTube/CDNs e executa FFmpeg localmente.

## Fluxo de uso

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

Quando um link de vídeo contém também `list=`, o aplicativo não presume que a playlist inteira deve ser baixada. A decisão é explícita:

```text
Vídeo dentro de playlist
├── Somente este vídeo   ← padrão seguro
├── Playlist completa
└── Cancelar
```

A mesma regra é usada para links detectados pelo clipboard. Para listas TXT, um link explícito `/playlist?list=...` continua sendo a forma indicada para solicitar a playlist inteira.

## Instalação

### Requisitos

- **Python 3.12** recomendado e usado no CI;
- **FFmpeg** instalado no sistema;
- conexão com a internet para pesquisa e downloads.

Clone o repositório público:

```bash
git clone https://github.com/Jczarf/public-youtube-downloader.git
cd public-youtube-downloader
./install.sh
./run.sh
```

Os scripts usam diretamente `.venv/bin/python`; não é necessário ativar o ambiente virtual.

Para escolher explicitamente o interpretador:

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

Sem FFmpeg, a aplicação abre normalmente, mas bloqueia os downloads que dependem dele e informa o requisito.

## Sessão autenticada do YouTube

O aplicativo **não lê cookies do navegador por padrão**. Em casos em que o YouTube exigir confirmação de sessão, execute explicitamente com o navegador desejado:

```bash
env YT_DLP_COOKIES_FROM_BROWSER=firefox ./run.sh
```

Também são aceitos navegadores compatíveis com `yt-dlp`, como Chrome, Chromium, Brave, Edge, Opera, Vivaldi e Safari.

O acesso acontece somente na execução em que a variável foi definida. Não exporte cookies para dentro do repositório e não versione arquivos de sessão.

Para playlists grandes, concorrência **1 ou 2** tende a ser mais conservadora quando o YouTube começa a limitar requisições.

## Dados locais

Preferências:

```text
$XDG_CONFIG_HOME/youtube-downloader/config.json
```

ou, normalmente:

```text
~/.config/youtube-downloader/config.json
```

Histórico:

```text
~/.config/youtube-downloader/history.json
```

Em sistemas POSIX, os arquivos são gravados com permissões privadas quando o sistema de arquivos suporta essa semântica.

O histórico guarda somente os dados necessários para a interface, como título, estado, formato, pasta, mensagem sanitizada e data. A URL original do vídeo não é persistida.

## Segurança e robustez

O projeto aplica validações antes de iniciar operações de rede ou escrita local:

- URLs externas ao YouTube são rejeitadas;
- somente rotas reconhecidas de vídeo, playlist e pesquisa são aceitas;
- links HTTP válidos são canonicalizados para HTTPS;
- um vídeo com `list=` não dispara uma playlist inteira silenciosamente;
- TLS não é desativado;
- FFmpeg ausente é detectado antes do download;
- configurações inválidas são normalizadas para valores seguros;
- pasta de destino precisa ser absoluta ou baseada em `~`, e a raiz `/` é recusada;
- configuração e histórico usam escrita atômica;
- URLs são removidas das mensagens persistidas no histórico;
- TXT é limitado a **2 MB**, **500 entradas** e **4096 caracteres por linha**;
- playlists são iteradas até o limite configurado, sem materializar toda a coleção de uma vez;
- transferências usam retries com backoff e perfil de rede conservador;
- novas instalações começam com **2 downloads simultâneos**;
- Security Audit executa scanner de segredos e `pip-audit`.

Veja também [`SECURITY.md`](SECURITY.md).

## Dependências principais

```text
PySide6==6.11.2
yt-dlp==2026.8.19
```

As versões de runtime são fixadas na baseline validada. Atualizações devem ser acompanhadas por nova execução dos testes e da auditoria de segurança.

## Testes

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

O CI também executa `pip check`, compila o código e instancia a GUI com `QT_QPA_PLATFORM=offscreen`.

Os testes cobrem, entre outros pontos, links `watch?v=...&list=...`, escolha entre vídeo e playlist, perfil de rede, cookies opt-in e cancelamento antes da resolução.

## Limitações conhecidas

- mudanças no YouTube podem exigir atualização do `yt-dlp`;
- alguns vídeos podem exigir uma sessão autenticada mesmo sendo públicos;
- FFmpeg é obrigatório para os fluxos suportados;
- cancelamento é cooperativo e pode não ser instantâneo durante resolução de metadados ou processamento externo;
- CI headless reduz regressões, mas não substitui inspeção visual e teste real em um desktop;
- aparência pode variar conforme fonte, compositor, escala e tema do sistema;
- o projeto não é um serviço comercial nem um backend de download.

## Status

**Aplicação funcional para uso local e projeto pessoal em evolução.**

## Autor

**Júlio Cézar** — estudante de Ciência da Computação e Técnico em Desenvolvimento de Sistemas.
