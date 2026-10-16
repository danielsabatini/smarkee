# 0035 — A CLI `sk` fala inglês com o usuário

- **Data:** 2026-10-16
- **Status:** Aceita. Abre uma exceção na regra do `AGENTS.md` §16.1 (textos de ajuda em pt-BR) e ajusta a decisão 0022 (padrão dos textos de ajuda).

## Contexto

A CLI misturava idiomas: a ajuda e as mensagens eram em português, e tudo o que o Typer, o Rich e as bibliotecas acrescentam (`Usage`, `Options`, `[required]`, o nome dos campos, os valores de estado) saía em inglês. O resultado, no mesmo comando, era uma tela como `Situação  enabled` ou um painel com título em português e rótulos em inglês. Os nomes dos campos já seguiam o contrato da API (`resourceId`, `operationId`), e os valores de estado são termos do domínio (`enabled`, `Ready`).

## Decisão

- **Todo texto que a CLI mostra ao usuário é em inglês:** ajuda (`--help`, descrição de comandos, opções e argumentos), títulos de painel, mensagens, avisos, erros, dicas, a página de retorno do login e o formato da data (`2026-10-16 11:02`, 24 h).
- **Os marcadores do padrão de ajuda (decisão 0022) passam para inglês:** `[String]`, `[Integer]` ou `[Boolean]`; `[env VARIABLE | file [section] key | default VALUE]`; `[required]` ou `[optional]`; e a linha `Resolution order: parameter → environment variable → configuration file (config.toml) → default`.
- **Nomes de campos e valores de estado** nas saídas seguem o contrato, em inglês (`resourceId`, `service`, `state`, `phase`, `observedRoles`, `enabled`, `disabled`, `none`, `renewed`).
- **Comentários e docstrings do código da CLI continuam em pt-BR**, como manda o `AGENTS.md` §16.1. Os documentos (README, CHANGELOG, decisões) também.
- **Recusas da API:** quando a CLI tem mensagem própria para a recusa (um `errorCode` conhecido ou `401`, `403`, `404`, `409`), mostra só ela, em inglês; o texto do Receiver (pt-BR) aparece apenas quando não há mensagem própria (por exemplo, `400` com o campo inválido), para a tela não misturar idiomas. Perde-se o detalhe dinâmico do servidor (como a contagem de recursos atrelados); a mensagem própria aponta os comandos para ver o que falta.
- **O que não muda:** o texto que vem de outros sistemas (páginas e e-mails do Zitadel, e as mensagens do Receiver sem mensagem própria na CLI) é mostrado como veio.

## Justificativa

- **Consistência:** uma tela com um idioma só. Nenhum texto de biblioteca (Typer, Rich, `argparse`) é traduzível sem remendos, então o único idioma coerente com o que a CLI não controla é o inglês.
- **Alcance:** a CLI é a interface pública da plataforma e pode ser usada fora do time e do Brasil; o inglês é o idioma comum de ferramentas de linha de comando.
- **Simplicidade e robustez:** sem tradução de texto de biblioteca e sem mistura, os testes verificam um vocabulário só.
- **Alternativa descartada:** manter português e traduzir o que for possível. Deixaria sempre um resto em inglês (`Usage`, `Options`) e exigiria manter as traduções.

## Consequências

- **`AGENTS.md` §16.1** ganha a exceção: a CLI fala inglês com o usuário; comentários, docstrings e documentos seguem em pt-BR.
- **Decisão 0022:** os marcadores e a linha de ordem de resolução passam para inglês (o mecanismo, `sk/help.py`, é o mesmo).
- **Quebra de compatibilidade (CLI em `0.x`):** quem lê a saída da CLI em script e dependia do texto em português (por exemplo, "Opção obrigatória ausente") precisa ajustar. Os códigos de saída e os campos de dados não mudaram.
- **Verificação:** a suíte da CLI e a jornada de ponta a ponta (`tests/e2e`) passam a afirmar os textos em inglês.
- **Não coberto:** os README e o CHANGELOG da CLI continuam em português; os e-mails e as páginas de login do Zitadel dependem do idioma configurado na instância.
