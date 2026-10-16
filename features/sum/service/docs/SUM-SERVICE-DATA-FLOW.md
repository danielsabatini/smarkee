# sum.service: fluxo de dados (da ligação até as roles no Zitadel)

Este documento segue o padrão de `features/core/user/docs/CORE-USER-DATA-FLOW.md`. Todos os passos estão
implementados e rodam no dev (Compose), verificados pela suíte e2e (`tests/e2e`), inclusive com falha de
componente. A decisão de desenho é a 0033 (`.decisions/0033-service-usage-manager.md`).

## 0. Visão geral

Ligar um serviço (`POST /v1/sum/services {"service": "ipm"}`) não concede roles diretamente. O pedido vira
uma mensagem `requested`, o Manager decide e grava, o Publisher publica o `desired`, o Reconciler compara com
o `observed` e manda uma `action`, o Executor concede no Zitadel, e o Observer lê de volta.

| Passo | Quem | Estado |
|---|---|---|
| 1 | Receiver: recebe o pedido e publica `requested` | Implementado, testado e no ar no dev |
| 2 | Manager: consome `requested`, decide, grava ligação, Operation e outbox | Implementado, testado e no ar no dev |
| 3 | Publisher: publica o `desired` do outbox | Implementado, testado e no ar no dev |
| 4 | Reconciler: decide e publica `action` | Implementado, testado e no ar no dev |
| 5 | Executor: concede as roles no Zitadel e publica `completed` ou `failed` | Implementado, testado e no ar no dev |
| 6 | Observer: lê o Zitadel e publica `observed` | Implementado, testado e no ar no dev |
| 7 | Manager: aplica `observed` e resultados (fase e Operation) | Implementado, testado e no ar no dev |

Diagramas: caminho de ligar [`flow/01-ligar-servico.svg`](flow/01-ligar-servico.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), desligar [`03`](flow/03-desligar-servico.svg), falhas no Manager e na mensageria
[`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação [`05`](flow/05-falhas-na-reconciliacao.svg) e no Executor
[`06`](flow/06-falhas-no-executor.svg). Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg).
Estados: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg).
Banco: [`database/01-er-fisico.svg`](database/01-er-fisico.svg).

### Identificadores

- `resourceId`: UUIDv7 atribuído pelo Receiver (o Manager não o gera). Recusas gravam o mesmo id.
- `operationId`, `requestDigest`: vêm do Receiver; a repetição de um `operationId` não grava de novo.
- `ownerUserId`: o `resourceId` do usuário dono (o `sub` do token). Vem do token, nunca do corpo.
- `actionId` = `<resourceId>.<desiredGeneration>.<operação>.<messageId do observed>`: chave de dedupe da `action`.

## 1. Receiver → NATS: `requested` (implementado)

O corpo do `POST` é `{"service": "<nome>"}` (`schemas/sum/service/api-create-request`). O Receiver valida o token
(audience `roles-sum`), confere a role `sum.<serviço>.enable`, atribui `resourceId` e `operationId`, calcula o
`requestDigest` e publica `requested-create` em `receiver.requested.sum.service.<resourceId>.create`, com
`Nats-Msg-Id` igual ao `operationId`. O `ownerUserId` vem do `sub` do token. O desligamento é `DELETE`, que confere
a `resourceVersion` e publica `requested-delete` (`.delete`). Detalhes da API: `receiver/README.md`; o contrato
descritivo é `receiver/openapi.json`.

Erros, todos no formato `api-error`: `400` entrada inválida (sem repetir o valor enviado), `401` sem token válido, `403`
sem a role da ação, `404` inexistente ou de outro dono, `409` serviço já ligado ou versão desatualizada, `422` reuso da
`Idempotency-Key` com outro pedido, `503` pedido não registrado (com `Retry-After`). Logo depois do `202`, a leitura pode
dar `404` até o Manager gravar a ligação e a Operation (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.1). Diagrama:
[`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg).

## 2. Manager consome `requested` e grava (implementado)

O consumer `sum-service-manager-requested` (pull, durável, ACK explícito) entrega a mensagem a
`transport/requested.py`:

1. valida o envelope e os dados (`MessageEnvelope` tolerante, `ServiceRequestedCreateData` ou
   `ServiceRequestedDeleteData`). Desvio do contrato, de módulo ou de versão `MAJOR` é `TERM`;
2. abre a transação, com o pool em autocommit (`transaction()` explícito);
3. chama `RequestedHandler.create` ou `.delete`;
4. ACK depois do `COMMIT`. Falha transitória do banco é `RETRY` com atraso.

### 2.1 Decisão (domínio puro, `domain/decision.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar | serviço fora do catálogo | recusa `service_unavailable` |
| criar | par dono + serviço já com ligação ativa | recusa `already_exists`, com o `resourceId` existente |
| criar | senão | aceita: `desired` com `present` e as roles do catálogo, copiadas agora |
| desligar | sem ligação ativa | recusa `not_found` |
| desligar | `resourceVersion` diferente da atual | recusa `conflict` |
| desligar | senão | aceita: `desired` com `absent` e `serviceRoles = []` |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `sum.service` (geração 1, versão 1, fase `Pending`), dentro de um savepoint. O
  índice único parcial `service_active_link` impede duas ligações ativas para o mesmo par, mesmo com pedidos
  concorrentes: se a violação acontecer, a recusa é `already_exists`.
- **Desligar aceito:** `UPDATE` da mesma linha: `lifecycle = absent`, geração + 1, versão + 1. A linha não é
  apagada: quem desliga mantém o histórico, e uma nova ligação cria outra linha.
- **Operation:** `INSERT` em `sum.service_operation` com `accepted` (com `desired_generation`) ou `rejected`
  (com o motivo, sem geração).
- **Outbox:** só nas aceitas, `INSERT` em `sum.service_outbox` com a mensagem `desired` (envelope sem
  `publishedAt` e `publishedBy`, que o Publisher preenche).

### 2.3 Repetição

Reentrega com o mesmo `operationId` não grava nada: `Duplicate`, e o ACK acontece. Pedidos concorrentes para
o mesmo par são resolvidos pelo índice único.

## 3. Outbox → NATS (implementado)

O Publisher (`sum-service-publisher`) lê as linhas pendentes em ordem de `sequence`, em lotes de 100, e para
cada uma:

1. valida o envelope completo de forma estrita e acrescenta `publishedAt` e `publishedBy: sum-service-publisher`;
2. publica em `manager.desired.sum.service.<resourceId>.changed`, com `Nats-Msg-Id` igual ao `messageId`;
3. marca `published_at` **depois** da confirmação do transporte.

Só uma instância publica por vez: a trava consultiva de sessão é mantida enquanto a instância publica, e é
reconquistada se a conexão cair. Envelope inválido ou recusa permanente do transporte param o lote, registram `ERROR`
com `sequence` e `message_id`, mantêm a mensagem pendente (a ordem é preservada) e tiram o Publisher de `ready`
(verificação `publication`), sem derrubar o processo (decisão 0018). Erro transitório tem recuo exponencial.

## 4. Reconciler (implementado)

O `desired` (stream `DESIRED`) e o `observed` (stream `OBSERVED`) chegam ao motor, junto com os resultados
(`RESULT`). O estado é um cache descartável: cada instância cria os próprios consumers (nome único por execução,
`DeliverLastPerSubject`, `inactive_threshold`) e reconstrói o último `desired`, `observed` e resultado de cada
ligação ao iniciar. A reavaliação periódica tem jitter. Antes de decidir, a decisão confere as guardas do loop: sem os dois estados, `desired` suspenso,
`observed` `unknown` ou vencido, observação causada por um resultado ainda não chegada, ação pendente da
mesma geração, e backoff após falha.

- **Ligação ativa** com roles faltando → `update` (`Drift`).
- **Ligação desligada** com alguma role do serviço presente → `update` (`RolesRemovalRequested`).

A `action` vai para `reconciler.action.sum.service.<resourceId>.update`, com `Nats-Msg-Id` igual ao `actionId`.
Diagrama: [`flow/05-falhas-na-reconciliacao.svg`](flow/05-falhas-na-reconciliacao.svg).

## 5. Executor (implementado)

O Executor consome todas as partições do `ACTION` (um consumer e um laço por partição no mesmo processo,
`max_ack_pending = 1`: uma ação por vez em cada recurso, até quatro recursos em paralelo; decisão 0018).

Antes de executar, cada `action` passa por:

1. **Validação da mensagem:** emissor `reconciler`, tipo `action`, módulo e tipo do recurso, versão `MAJOR` e
   `actionId`. Mensagem fora disso é descartada e registrada. O `desired` lido do transporte também precisa ser do
   emissor `manager`.
2. **Idempotência:** um `actionId` com `completed` ou `failed` permanente já registrado não é executado de novo; o
   resultado é republicado com o mesmo `Nats-Msg-Id` (o transporte deduplica).
3. **Revalidação contra o `desired` vigente** (`docs/RESOURCE-CONTROL-SECURITY.md` §7): sem `desired` ou com geração
   diferente é `failed` `StaleAction`; `reconciliation` suspenso é `failed` `Suspended`; `lifecycle` ausente ou
   inválido, ou operação não permitida, é `failed` `Rejected`. Todas permanentes. Não existe `lifecycle` padrão:
   sem ele o Executor não concede nada.

Erro transitório do Zitadel volta a mensagem à fila; recusa permanente vira `failed` com o motivo. Diagrama:
[`flow/06-falhas-no-executor.svg`](flow/06-falhas-no-executor.svg).

- **Ligar:** garante as roles pedidas, no projeto `roles-ipm`. Cria a autorização se não existe; senão, acrescenta
  só as que faltam. Repetir não muda nada.
- **Desligar:** tira só as roles do serviço, mantém as demais, e remove a autorização quando não sobra nenhuma.

Toda concessão passa pela conta `sum-service-executor`, que tem `PROJECT_GRANT_OWNER` só no Grant de
`roles-ipm` (decisão 0032). O Zitadel recusa qualquer outra role. Isso foi verificado no dev com o provider
real: `core.user.get` em `roles-core` e `ipm.organization.admin` em `roles-ipm` foram recusados.

## 6. Observer (implementado)

Lê o Zitadel só de leitura (conta `sum-service-observer`): se o usuário existe e as autorizações nos
projetos de roles. Como o Reconciler, cada instância cria os próprios consumers (`DeliverLastPerSubject`) e
reconstrói o que precisa observar. A observação periódica tem jitter, e com várias réplicas cada uma observa só os
recursos da sua partição (`hash(resourceId) mod count`, `SUM_SERVICE_OBSERVER_PARTITION_{INDEX,COUNT}`). Um `desired`
sem `lifecycle` válido não é observado. Produz:

- `present`, com `serviceRoles` = as roles do catálogo que o usuário tem;
- `absent`, só quando o Zitadel confirma que o usuário não existe (404 com detalhe);
- `unknown`, para qualquer falha de leitura. Erro de leitura nunca vira `absent`.

A mensagem `observed` sai em `observer.observed.sum.service.<resourceId>.changed`, com `causationId` quando é
a resposta a um resultado.

## 7. Manager aplica `observed` e resultados (implementado)

O Manager também consome `OBSERVED` e `RESULT` (consumers `sum-service-manager-{observed,completed,failed}`) e os
aplica ao SSOT, cada mensagem numa unidade atômica com a linha da ligação bloqueada:

- **`observed`:** ignorado se mais antigo que o último aplicado (por `observedAt`). `unknown` só atualiza `presence` e
  `observed_at`. Senão grava `observed` e calcula a fase: `Ready` quando convergiu (ligada com as roles do `desired`, ou
  desligada sem roles), `Reconciling` quando não.
- **Operation:** `Reconciling` marca as pendentes até a geração atual como `in_progress`; `Ready` as conclui
  (`completed`, com `completed_at`).
- **Resultado:** registrado uma vez por `actionId` (`sum.service_action_result`). Um `failed` marca a fase `Failed` da
  geração da ação e soma `failure_count`; a próxima observação recalcula a fase.

## 8. Estados

- **Fase** (`phase`): `Pending` ao gravar ou ao desligar, `Reconciling`, `Ready` e `Failed` (não terminal).
  Diagrama: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg). `completed` não é `Ready`: só a observação
  compatível converge.
- **Operation:** `accepted`, `in_progress`, `completed` e `rejected` (com motivo, sem geração). Limitação: ela não vira
  `failed`; a falha aparece na fase `Failed` da ligação. Diagrama: [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `sum.service` | Manager | Receiver (view `sum.service_v1`) |
| `sum.service_operation` | Manager | Receiver (view `sum.service_operation_v1`) |
| `sum.service_action_result` | Manager | Manager (dedupe por `actionId`) |
| `sum.service_outbox` | Manager (insere) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer |
| `OBSERVED` | Observer | Reconciler, Manager |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer, Manager |
| Zitadel (autorizações em `roles-ipm`) | Executor | Observer (leitura) |

## 10. Verificação (2026-10-15, dev)

Com os seis componentes no Compose, a suíte e2e (`tests/e2e`) liga e desliga `ipm` com um solicitante real e confere:
`202` com o contrato de aceite, Operation até `completed`, fase `Ready` com as roles observadas, listagem, `409` no
duplicado, desligar com revogação das roles e `Ready` com `lifecycle absent`. Todas as respostas são validadas contra os
schemas. O teste de caos derruba o Manager, o Executor e o Publisher durante um pedido, e reinicia o Reconciler e o
Observer no meio de uma ligação pendente: em todos os casos o loop converge. Os recursos de teste são removidos ao final
(a ligação é desligada pela API; só então a linha é apagada).
