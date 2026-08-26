# Checklist de publicação

A árvore atual foi sanitizada e o branch `main` foi recriado a partir de uma **baseline limpa, sem o histórico legado anterior**.

## Concluído

- [x] remover lista pessoal do estado atual;
- [x] remover componentes legados em CustomTkinter;
- [x] remover bypass de validação TLS;
- [x] adicionar testes e workflow de CI;
- [x] adicionar licença e política de segurança;
- [x] recriar o histórico alcançável do `main` a partir da árvore sanitizada;
- [x] adicionar verificação automática de segredos óbvios no CI.

## Antes de tornar público

- [ ] confirmar CI verde na baseline atual;
- [ ] executar a GUI em Linux desktop real;
- [ ] substituir mockup por screenshot real quando o visual estiver validado;
- [ ] executar scanner dedicado de segredos no clone final, além da checagem básica do projeto;
- [ ] revisar visualmente todos os arquivos que serão publicados.

> A reescrita do branch remove o histórico antigo da navegação normal e da ancestralidade do `main`. Objetos Git antigos podem permanecer temporariamente retidos pela infraestrutura do provedor. Se algum segredo real já tivesse sido publicado, a ação correta continuaria sendo revogá-lo/rotacioná-lo.
