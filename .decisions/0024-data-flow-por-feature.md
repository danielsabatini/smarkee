# 0024 — Um documento de fluxo de dados (`DATA-FLOW`) por feature

- **Data:** 2026-10-14
- **Status:** Aceita. Complementa a decisão 0015 (componentes por papel) e a 0017 (estrutura interna e testes e2e).

## Contexto

Os diagramas de `docs/flow/` de uma feature mostram quem fala com quem, mas não os dados. Para entender o que um comando grava, é preciso abrir o Receiver, o Manager, o Publisher e os schemas e montar o quadro à mão: qual rota é chamada, qual o payload de cada mensagem, qual a query e quais linhas mudam. Cada feature nova (a Organization é a próxima) repetiria o problema, e cada autor escolheria uma estrutura diferente.

## Decisão

Toda feature (`features/<módulo>/<tipo>`) tem **um** documento de fluxo de dados, com nome e estrutura fixos.

- **Local e nome:** em maiúsculas, como os demais documentos (`README.md`, `AGENTS.md`, `docs/*.md`). `features/<módulo>/<tipo>/docs/<MÓDULO>-<TIPO>-DATA-FLOW.md` (por exemplo, `features/core/user/docs/CORE-USER-DATA-FLOW.md`). Fica na raiz de `docs/`; as subpastas (`architecture/`, `database/`, `flow/`, `state/`) guardam só os diagramas e suas fontes.
- **Idioma:** texto em pt-BR; rotas, campos, mensagens e SQL como no código (`AGENTS.md` §16.1 e §39).
- **Conteúdo:** os dados de **um caso completo** (a criação do recurso, do comando do cliente até a convergência), com um único exemplo coerente do início ao fim, e um resumo das demais operações. Cada passo mostra, no mesmo molde: quem executa; a entrada; a saída (rota ou Subject, cabeçalhos, payload com os campos e formatos); e o que é gravado (tabela, colunas, query).
- **Estrutura, nesta ordem** (os títulos podem citar os atores e a rota concretos):
  1. **Cabeçalho:** escopo, a origem dos exemplos (código e schemas, ou execução real) e as fontes de verdade que o documento não substitui.
  2. **Visão geral:** tabela dos passos (de → para, meio, o que sai, o que é gravado), os identificadores que ligam o fluxo (quem cria, formato, papel) e os valores usados nos exemplos.
  3. **Entrada:** o comando do cliente e a chamada à API (rota, autenticação, corpo, respostas e erros).
  4. **Mensagem `requested`:** como as identidades são geradas e o envelope completo, com Stream, Subject e cabeçalhos.
  5. **Gravação do Manager:** as queries na ordem em que executam, o estado de cada tabela ao final, a repetição e a rejeição.
  6. **Outbox e Publisher:** a linha do outbox, o payload de `desired`, a leitura do lote e o que o Publisher acrescenta.
  7. **Continuação do loop até a convergência:** `observed`, `action`, `completed` ou `failed` e `updated`, cada um com o payload e o que o Manager grava, mais a linha do tempo do banco.
  8. **Leitura:** as rotas `GET` e as views que as servem.
  9. **Demais operações:** remoção e as outras que o tipo tiver, em resumo.
  10. **Mapa de gravações:** mensagem por tabela e privilégio por papel de banco, mais as divergências e limitações conhecidas.
- **Fonte única da verdade (`AGENTS.md` §1.1):** o documento mostra um caso concreto e **linka** as especificações (`docs/MESSAGING.md`, `docs/NATS.md`, `docs/SSOT.md`, `docs/POSTGRESQL.md`), os schemas e a migração; não repete as regras.
- **Exemplos verificáveis:** valores fictícios (`example.com`, UUIDs de exemplo), sem credenciais (`AGENTS.md` §4.1), conferidos contra o código, os schemas e a migração. Quando não vierem de uma execução real, o documento diz isso.
- **Manutenção:** mudou um contrato de mensagem, uma rota, um schema, uma migração ou um privilégio da feature? O mesmo trabalho atualiza o `DATA-FLOW`. Em caso de divergência com outro documento da feature, vale o código (a migração, para o banco), e a divergência é registrada no próprio `DATA-FLOW`.
- **Escopo:** o documento descreve só a feature; não entra em `CHANGELOG.md` nem em `ROADMAP.md` (`AGENTS.md` §36.3).

## Justificativa

Um documento por feature, com estrutura fixa, responde "o que trafega e o que é gravado" sem ler o código, e permite comparar features lado a lado. Alternativas descartadas: um documento único na raiz de `docs/`, que misturaria dados de tipos diferentes e envelheceria no primeiro tipo novo; e acrescentar os dados ao `README.md` da feature, que já é longo e trata de papéis, segurança e operação.

## Consequências

- `features/core/user/docs/CORE-USER-DATA-FLOW.md` é o primeiro e o modelo.
- A Organization (`features/ipm/organization`) foi refeita a partir do User e tem o seu `IPM-ORGANIZATION-DATA-FLOW.md` (decisão 0038).
- Agentes e skills que criam ou alteram features linkam esta decisão e não repetem a estrutura (`AGENTS.md` §24.1).
