# Segurança

Este projeto é uma aplicação local e não deve ser executado com privilégios administrativos.

## Princípios da edição pública

- não desativa a validação TLS do `yt-dlp`;
- não aceita URLs externas ao YouTube como se fossem entradas válidas;
- arquivos baixados e listas pessoais ficam fora do Git;
- monitor de clipboard é opt-in;
- falhas do downloader não são ocultadas por `ignoreerrors`;
- arquivos de configuração permanecem no diretório XDG do usuário.

## Relato de vulnerabilidades

Não publique chaves, cookies, URLs privadas ou outros dados sensíveis em issues. Prefira contato privado com o autor.

## Limite de segurança

A aplicação delega extração e download ao `yt-dlp` e processamento ao FFmpeg. Isso reduz código próprio, mas não transforma entradas ou mídias remotas em conteúdo confiável. Mantenha dependências atualizadas e use somente fontes que você pretende acessar.
