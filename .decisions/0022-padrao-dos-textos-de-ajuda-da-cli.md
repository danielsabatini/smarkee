# 0022 — Padrão dos textos de ajuda da CLI

- **Data:** 2026-10-12
- **Status:** Aceita. Complementa a decisão 0021 (apresentação com Rich); não a substitui.

## Contexto

A ajuda da CLI `sk` (`--help`) descrevia as opções com frases soltas, misturava detalhes de implementação (protocolo de login, endereço de retorno local, nomes de arquivos internos, gateway, módulo) e não deixava claro, para cada opção, o tipo do valor, de onde ele pode vir e se é obrigatório. O usuário avaliou várias formas de apresentar isso e escolheu o padrão abaixo.

## Decisão

- **Linguagem para o usuário final.** Os textos de ajuda dizem o que o comando e a opção fazem, sem detalhes de implementação. Exemplos do que não aparece: nome do protocolo de autenticação, endereço de retorno local, nome do arquivo de credenciais, "gateway", "módulo".
- **Comando.** Descrição curta (o que faz) seguida da linha `Ordem de resolução: parâmetro → variável de ambiente → arquivo de configuração (config.toml) → padrão`. No `sk auth init` o arquivo não entra na ordem, porque o comando não lê o arquivo que cria.
- **Opção.** `<descrição> [Tipo] [fontes] [situação]`, em que:
  - **Tipo:** `[String]` ou `[Booleano]` (flags). O Typer não mostra o tipo das flags.
  - **Fontes:** `[env VARIÁVEL | arquivo [seção] chave | padrão VALOR]`, na ordem de resolução, **somente as que existem**. Sem nenhuma (valor só por parâmetro), o bloco é omitido.
  - **Situação:** `[obrigatório]` ou `[opcional]`, derivada do padrão: sem padrão, é obrigatória; com padrão, é opcional. Não há campo separado, para não existir "obrigatório com padrão".
- **Cores** (só em terminal interativo): tipo em ciano, fontes em amarelo, `[obrigatório]` em vermelho e `[opcional]` em magenta.
- **Obrigatoriedade validada pelo comando.** As opções obrigatórias sem fonte alternativa (`sk register --name`, `--surname`, `--email`) não são `required` no Typer: o comando as exige e encerra com código 2 e a mensagem "Opção obrigatória ausente". Motivo: o Typer imprime um `[required]` extra que não pode ser ocultado.
- **Implementação:** `sk/ajuda.py` (`comando()` e `opcao()`) é o único lugar que monta esses textos. O markup do Rich exige escapar os colchetes, inclusive os do próprio formato.
- **Testes:** `tests/unit/test_ajuda.py` verifica o formato de todas as opções e a ordem das fontes, o tipo booleano das flags, as obrigatórias, o `init` sem a fonte de arquivo e a validação de obrigatórios.

## Justificativa

- Dizer, em cada opção, o tipo, de onde vem o valor e se é obrigatório evita consultar a documentação para usar o comando.
- Mostrar só as fontes que existem remove ruído: três "nenhum" seguidos pareciam um erro e escondiam o que é relevante.
- Derivar a situação do padrão deixa uma única regra e elimina a combinação incoerente.
- **Alternativas descartadas:** delimitar os segmentos com `<…>` (o Typer pinta todo texto entre `<` e `>` de amarelo, o que anula as cores); marcar a obrigatoriedade com `*` no início da descrição (confuso, e a coluna do `*` do Typer vem junto com o `[required]`).

## Consequências

- Todo novo comando e opção usa `comando()` e `opcao()`. Um texto fora do padrão falha em `test_ajuda.py`.
- As opções obrigatórias do `register` dependem da validação do comando, e não do Typer.
- Os textos do próprio Typer (`--help`, `--install-completion`, `--show-completion`) continuam em inglês. Traduzi-los fica como pendência.
