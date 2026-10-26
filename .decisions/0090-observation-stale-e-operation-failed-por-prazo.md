# 0090 — `ObservationStale` e Operation `failed` por prazo esgotado

- **Data:** 2026-10-26
- **Status:** Aceita e implementada no template `manager-handlers` (as 8 features que o usam).
- **Origem:** incidente de 2026-10-26. A permission de teste `e2e.test.pde38f7` (módulo sem projeto de roles) recebeu `delete`, o Observer devolveu `unknown` para sempre e o recurso ficou em `Deleting` sem aviso, sem condition e com a Operation `in_progress`. O contrato (`RESOURCE-CONTROL-LOOP.md` §10.1) já previa `ObservationStale`, mas nenhuma feature a implementava.

## Contexto

- O Manager não alterava fase nem prazo diante de `unknown` (decisões `0071` e `0078`): um recurso nunca lido ficava indefinidamente no estado anterior, e o `progressDeadline` só contava observações que **divergem**.
- A referência é o Deployment do Kubernetes: passado o prazo, `Progressing` fica `False`, o rollout é dado como falho e o controlador **segue tentando** (decisão `0078`).

## Decisão

1. **Condition `ObservationStale` (Manager, template).** `lastTransitionAt` marca a primeira `unknown` da sequência.
   - `False`/`ObservationUnknown` enquanto a sequência está dentro do prazo;
   - `True`/`Timeout` quando o recurso permanece `unknown` por mais que o `progressDeadline` (mesmo parâmetro, sem novo campo de contrato), com o aviso `observation stale`, uma vez só;
   - uma observação conclusiva encerra a sequência: a condition sai se estava `False`, ou fica `False`/`ObservationResumed` se estava `True`.
2. **Fase.** Passado o prazo em `unknown`, um recurso que **não está `Ready`** (com trabalho pendente: `Pending`, `Reconciling` ou `Deleting`) vai para `Failed`, como no `ProgressDeadlineExceeded`. Um recurso `Ready` que passa a `unknown` mantém `Ready` e só ganha a condition (nada está pendente). O loop não é suspenso: ao voltar uma leitura conclusiva o recurso converge (`Ready` ou remoção) sozinho.
3. **Operation `failed` por prazo.** Quando o prazo de progresso ou de observação se esgota, as Operations da geração atual ainda abertas terminam `failed` (como já ocorre no `failureLimit`), em vez de ficarem `in_progress` para sempre. O `operationStatus` não muda de enum. Se o recurso convergir depois, a Operation segue `failed`: ela descreve o pedido, e o recurso volta a `Ready` por conta própria.

## O que permanece, o que se acrescenta (§2.6)

- Permanece: `Progressing`, o `progressDeadline`, o backoff do Reconciler e a regra de que `unknown` nunca vira `absent`.
- Acrescenta: a condition `ObservationStale`, a transição para `Failed` por `unknown` e o encerramento da Operation por prazo.
- Substitui: nada.

## Fora desta decisão

A Operation `superseded` (substituída por outra geração antes de convergir) continua `failed`. Separar os dois exige acrescentar um valor a um enum fechado em schema, SQL, modelos gerados e CLI, e será decidido à parte.
