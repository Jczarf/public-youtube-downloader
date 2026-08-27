# Segurança

Este projeto é uma aplicação desktop **local** e não deve ser executado com privilégios administrativos.

## Modelo de execução

- não abre porta TCP/HTTP;
- não expõe API ou servidor local;
- GUI, fila, preferências e histórico executam na máquina do usuário;
- acessos de rede são de saída, realizados pelo `yt-dlp` para pesquisar e baixar conteúdo do YouTube/CDNs;
- FFmpeg executa localmente para conversão, merge e recortes.

## Princípios da edição pública

- validação TLS do `yt-dlp` permanece habilitada;
- URLs são aceitas apenas em hosts oficiais do YouTube e em rotas reconhecidas de vídeo, playlist ou pesquisa;
- URLs `http://` aceitas são canonicalizadas para HTTPS antes do processamento;
- rotas de redirecionamento, canais e páginas genéricas não são tratadas como vídeo;
- títulos e mensagens externas são exibidos como texto simples na GUI;
- clipboard é opt-in e **somente da sessão**: reiniciar o aplicativo volta ao estado desligado;
- FFmpeg ausente bloqueia o início de downloads;
- configuração e histórico usam escrita atômica e, em sistemas POSIX, permissões `0600` em diretório privado `0700`;
- o histórico não persiste a URL do vídeo e redige URLs encontradas em mensagens de erro;
- arquivos TXT são limitados por tamanho, quantidade de entradas e comprimento de linha;
- arquivos baixados e listas pessoais ficam fora do Git;
- dependências da aplicação são fixadas na baseline validada;
- GitHub Actions usa permissões somente de leitura e checkout sem persistência de credenciais;
- o workflow **Security Audit** verifica segredos na árvore/histórico e vulnerabilidades conhecidas das dependências Python com `pip-audit`.

## Limites

A aplicação delega extração e download ao `yt-dlp` e processamento ao FFmpeg. Conteúdo remoto continua sendo conteúdo não confiável, e atualizações do YouTube podem exigir atualização consciente do `yt-dlp` e nova validação do projeto.

O cancelamento é cooperativo: durante determinadas fases de resolução de metadados ou processamento externo, a interrupção pode não ser instantânea. Ao fechar o aplicativo, novas atualizações da interface são bloqueadas e as filas são canceladas/limpas antes da saída.

## Relato de vulnerabilidades

Não publique chaves, cookies, URLs privadas ou outros dados sensíveis em issues. Prefira um canal privado com o autor.
