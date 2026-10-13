# 0021 — Apresentação da CLI com Rich

- **Data:** 2026-10-12
- **Status:** Aceita. Complementa a decisão 0008 (CLI em Typer e Pydantic); não a substitui.

## Contexto

A CLI `sk` imprimia mensagens de texto puro, com erros e avisos em frases soltas. O Typer já instala o Rich como dependência, e o `sk` não o usava. O usuário avaliou um painel de sucesso e um padrão de erro e pediu que fosse adotado em todos os comandos.

## Decisão

- Toda saída da CLI passa pelo módulo `sk/ui.py`. Nenhum comando chama `typer.echo` diretamente para mensagens ao usuário.
- **Sucesso:** painel (`panel`) com pares rótulo e valor, na saída padrão. Uma linha de orientação (`note`) abaixo, com o próximo passo.
- **Erro:** título em vermelho (`error`), a causa e, quando houver, uma dica de correção. Vai para a saída de erro, com o mesmo código de saída de antes.
- **Aviso:** linha amarela na saída de erro (`warning`).
- **Passo interativo com URL** (login): painel destacado na saída de erro (`url_panel`), para copiar.
- **Segredos:** a apresentação nunca recebe nem mostra tokens, senhas ou o conteúdo de credenciais. Quem chama passa só o que pode ser mostrado.
- **Cor e caixas:** só em terminal interativo. O Rich respeita `NO_COLOR`.
- **Dependência:** `rich` está declarada explicitamente no `pyproject.toml`, porque o código a importa diretamente.
- **Testes:** verificam os valores e os códigos de saída, e não a formatação de caixas e cores.

## Justificativa

- Uma saída consistente facilita a leitura e reduz erros de interpretação (por exemplo, quando o usuário precisa copiar um endereço ou corrigir um campo).
- Centralizar a apresentação em um módulo evita divergência entre comandos e facilita trocar o estilo sem tocar na lógica.
- Declarar a dependência evita que ela só funcione porque o Typer a instala.

## Consequências

- Todos os comandos atuais (`auth init`, `auth login`, `register`) seguem o padrão. Novos comandos devem usar `sk/ui.py`.
- O `sk user` não será implementado (decisão do usuário); `sk auth whoami` e `sk ipm organization` nascem com o padrão.
- A saída passa a conter caracteres de caixa e símbolos (✓, ✗, →). Em terminais sem suporte, o Rich usa substitutos, mas a saída ainda deve ser legível sem cor.
