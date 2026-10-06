# 0003 — Serialização por recurso, publicação sequencial e recuperação do SSOT

- **Data:** 2026-10-06
- **Status:** Aceita

## Contexto

Três lacunas de corretude foram identificadas na revisão do SSOT:

1. O Manager consome `observed` e resultados em paralelo. A atualização de `observed` conferia apenas `observedAt`, e não a versão do registro. Duas instâncias calculavam `conditions` e `phase` sobre o mesmo estado lido, e a última gravação sobrescrevia a outra.
2. A publicação do outbox não definia o modo de envio. Com envio em paralelo, uma mensagem antiga repetida após um erro podia ser gravada depois de uma nova e virar o último estado retido no stream.
3. O modelo afirmava que a geração não retrocede após uma restauração a um ponto no tempo, sem um mecanismo para isso. Na prática, a restauração faz a geração voltar, e uma nova alteração reutilizaria uma geração já publicada com outro conteúdo.

## Decisão

- **Toda unidade atômica do Manager começa bloqueando a linha do recurso** (`SELECT ... FOR UPDATE`). A concorrência otimista por `resourceVersion` continua protegendo o solicitante externo.
- **O relay publica de forma sequencial**: a próxima mensagem só é publicada depois da confirmação da anterior, e um erro interrompe o lote. O relay usa uma única instância por trava consultiva, sem `FOR UPDATE` nas linhas do outbox, e confere a posse da trava antes de cada lote.
- **Procedimento de recuperação** após restauração, executado por infraestrutura com o Manager e o relay parados:
  1. descartar o outbox pendente;
  2. comparar cada recurso com o último `desired` retido no transporte;
  3. quando necessário, avançar a geração para além da geração do transporte e republicar;
  4. listar, sem alterar, os recursos que existem só no transporte.

## Justificativa

- O bloqueio da linha é o mecanismo mais simples que serializa todos os fluxos de um recurso. Ele também sustenta a ordem do outbox, e cada transação bloqueia uma única linha, sem ciclos de espera.
- A publicação sequencial elimina a reordenação sem exigir controle de concorrência no transporte.
- A recuperação explícita torna verdadeira a invariante "uma geração publicada nunca é reutilizada com outro conteúdo". Ela é uma exceção deliberada à regra de que a geração só muda quando a especificação muda.

## Consequências

- Os papéis de login de runtime recebem `lock_timeout`, `statement_timeout` e `idle_in_transaction_session_timeout`, para que uma instância travada não segure o bloqueio indefinidamente. A verificação mostrou que esses parâmetros precisam ser definidos no papel de login, e não no papel de função.
- A vazão do relay é limitada a uma publicação por vez por tabela de outbox. Se não bastar, o caminho previsto é particionar o relay por hash de `resource_id`.
- O teste periódico de restauração passa a incluir o procedimento de recuperação.
- Um failover assíncrono do banco que perca transações confirmadas é tratado como restauração.
