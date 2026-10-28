# sum.service: fluxo de dados (da ligação até as permissões no Zitadel)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de `features/core/account/docs/CORE-ACCOUNT-DATA-FLOW.md`. Segue **os dados** de uma ligação de serviço: qual rota é chamada, qual é o payload de cada mensagem, o que cada componente grava e com qual privilégio. A API síncrona é a [decisão 0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md); o loop unificado no Controller é a [0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md); as projeções locais, sem chamadas HTTP entre features, a [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md); e o SUM, a [0033](../../../../.decisions/0033-service-usage-manager.md).

**Origem dos exemplos.** Montados a partir do código e dos schemas, **não** de uma execução da stack nova (a suíte `tests/e2e` foi reescrita e ainda não foi executada contra os contêineres novos). Fontes de verdade: contratos em [`schemas/sum/service/`](../../../../schemas/sum/service), tabelas em [`migrations/`](../migrations), semântica em [`docs/messaging/MESSAGING.md`](../../../../docs/messaging/MESSAGING.md), [`docs/messaging/NATS.md`](../../../../docs/messaging/NATS.md), [`docs/data/SSOT.md`](../../../../docs/data/SSOT.md) e [`docs/data/POSTGRESQL.md`](../../../../docs/data/POSTGRESQL.md).

**Comando.** `sk sum service enable|disable|get|list` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/sum/services` (via gateway) | `{service}` | nada |
| 2 | API → banco | SQL, uma transação | `201 Resource` | `sum.service`, `sum.service_outbox` (o `desired`), `sum.service_idempotency` |
| 3 | Publisher → Controller | NATS, Stream `DESIRED` | `desired` | `sum.service_outbox.published_at` |
| 4 | Controller → Zitadel; Controller → banco | HTTP no Zitadel; SQL, uma transação | (nada publicado) | as autorizações no Zitadel; `sum.service` (observado, fase, conditions), `sum.service_outbox` |
| 5 | Publisher → consumidores | NATS, Stream `UPDATED` | `updated` (a cada mudança de fase) | `sum.service_outbox.published_at` |

Só a **API** admite pedidos e escreve o `desired` no SSOT; só o **Controller** escreve o estado observado, a fase e as conditions. O Publisher só marca `published_at`. O tipo não tem Operation nem os Streams `REQUESTED`, `OBSERVED`, `ACTION` e `RESULT` (decisões 0096 e 0098).

### Identificadores

- `resourceId`: UUIDv7 atribuído pela API. O recurso é o **par dono + serviço**: religar um par desligado reaproveita o `resourceId`.
- `ownerAccountId`: o `resourceId` do usuário dono (o `sub` do token). Vem do token, nunca do corpo. Vira o usuário no Zitadel.
- `messageId` (UUIDv7): é o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. `correlationId` é o mesmo em toda a cadeia.

## 1. CLI → API: `POST /v1/sum/services`

O corpo é `{"service": "<nome>"}` (`schemas/sum/service/api-create-request`). A API valida o token (audience `roles-sum`) e confere a permissão `sum.<serviço>.enable`. O desligamento é `DELETE /v1/sum/services/{resourceId}?resourceVersion=` (permissão `sum.<serviço>.disable`). Detalhes em `src/sum_service/api/README.md`; o contrato descritivo é `openapi.json`.

Erros, todos no formato `api-error`: `400` entrada inválida (sem repetir o valor enviado), `401` sem token válido, `403` sem a permissão da ação, `404` inexistente ou de outro dono, `409` (`ServiceNotAvailable`, `AlreadyEnabled`, `BillingAccountRequired`, `ResourcesAttached`, `Conflict` por versão), `422` reuso da `Idempotency-Key` com outro conteúdo, `503` projeção ainda não sincronizada (`ProjectionSyncPending`, com `Retry-After`).

## 2. Admissão síncrona (API → banco)

Numa única transação (`store/admission.py`, `http/admission.py`), com o par dono + serviço travado (`lock_pair`):

1. **Replay:** com `Idempotency-Key` já gravada para o solicitante, devolve o recurso se o conteúdo é o mesmo, ou `422` se difere.
2. **Regras (`domain/`):**

| Pedido | Condição | Resultado |
|---|---|---|
| ligar | serviço fora do catálogo | `409 ServiceNotAvailable` |
| ligar | par já ligado | `409 AlreadyEnabled` |
| ligar | dono sem Billing Account (projeção de `bsm.account`) | `409 BillingAccountRequired` |
| ligar | senão | aceita: `desired` com `present`, `servicePermissions` e `managedPermissions` do catálogo, copiadas agora |
| desligar | sem ligação do solicitante | `404` |
| desligar | `resourceVersion` diferente da atual | `409 Conflict` |
| desligar `ipm` | dono com Organizations (projeção de `ipm.organization`) | `409 ResourcesAttached` |
| desligar | senão | aceita: `desired` com `absent` e `servicePermissions = []` |
| desligar | par já desligado | `202` com o recurso, sem gravar nada |

3. **Gravação:** ligar faz `INSERT` em `sum.service` (geração 1, versão 1, fase `Pending`); religar faz `UPDATE` da mesma linha (`lifecycle = present`, geração + 1, versão + 1). Desligar faz `UPDATE` (`lifecycle = absent`, geração + 1, versão + 1): **a linha não é apagada**. O `desired` vai para `sum.service_outbox` (envelope `emitter = api`), e a chave de idempotência para `sum.service_idempotency`. O índice único parcial `service_active_link` garante uma única ligação ativa por par, mesmo com pedidos concorrentes.

As pré-condições leem **projeções locais** do `DESIRED` de `ipm.organization` e `bsm.account`, mantidas pela API; sem chamadas HTTP a outras features (decisão 0100).

## 3. Outbox → NATS

O Publisher lê as linhas pendentes em ordem de `sequence`, em lotes de 100, e para cada uma: valida o envelope completo de forma estrita, acrescenta `publishedAt` e `publishedBy`, publica em `manager.<desired|updated>.sum.service.<resourceId>.changed` com `Nats-Msg-Id` igual ao `messageId`, e marca `published_at` **depois** da confirmação. Só uma instância publica por vez (trava consultiva de sessão). Envelope inválido ou recusa permanente param o lote, mantêm a mensagem pendente e tiram o Publisher de `ready`, sem derrubar o processo (decisão 0018).

## 4. Controller: ciclo atômico por ligação

O Controller consome `manager.desired.sum.service.>` (consumer por instância, `DeliverLastPerSubject`) e enfileira o `resourceId` numa fila com deduplicação e backoff; uma reavaliação periódica (com jitter) enfileira todas as ligações `active`. Para cada uma, numa transação com a linha bloqueada (`FOR UPDATE`):

1. **Observa** o usuário dono (`GET /v2/users/{id}`: `404` é `absent` com `servicePermissions: []`; outra falha é `unknown`, que nunca autoriza ação) e as autorizações nos projetos de permissões, limitadas às `managedPermissions`.
2. **Decide** (`domain/decision.py`): `enable` se falta uma `servicePermission` ou sobra uma gerenciada que já não é desejada; `disable` se a ligação está desfeita e o usuário ainda tem permissões gerenciadas; nada se convergiu.
3. **Age** (`engine/actions.py`), idempotente: `enable` concede por projeto do módulo da permissão e revoga `managed − wanted`; `disable` tira só as gerenciadas e remove a autorização que ficar vazia, mantendo as de outros serviços. **Reobserva**.
4. **Grava** `observed`, `presence`, `phase` e `conditions` e, se algo mudou, o `updated` no outbox; `Ready` só vem de uma observação posterior à geração (decisão 0072). Ao atingir o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.

A ligação desfeita convergida fica `Ready` com `observed.servicePermissions = []`, e a linha permanece. Toda concessão usa a conta `sum-service-controller`, com `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm` (decisão 0032): o Zitadel recusa qualquer outra permissão.

### 4.1 Rollout do catálogo (decisão 0079)

Na partida, antes dos consumers, o Controller compara o `desired` de cada ligação com o que o catálogo atual produziria e, onde difere, grava uma geração nova (`requested_by = system:catalog`) com o `desired` correspondente no outbox. Repetir não grava nada.

### 4.2 Conta removida (decisão 0044)

Um segundo consumer lê `manager.updated.core.account.>`. No `updated` com `removed`, apaga as ligações do dono (`DELETE FROM sum.service WHERE owner_account_id = …`). Repetir não tem efeito.

## 5. Estados

`phase`: `Pending` ao gravar ou ao desligar, `Reconciling`, `Ready` e `Failed` (não terminal). A convergência se lê no recurso (`observedGeneration` igual a `desiredGeneration`, com `phase` `Ready`); não há Operation.

## 6. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `sum.service` | API (admissão); Controller (observação, remoção da conta) | API (view `sum.service_v1`), Controller |
| `sum.service_outbox` | API e Controller (inserem) | Publisher (lê e marca `published_at`) |
| `sum.service_idempotency` | API | API |
| `DESIRED` | Publisher | Controller; API (projeções de `ipm.organization` e `bsm.account`) |
| `UPDATED` | Publisher | Controller (`core.account` removida); consumidores externos |
| Zitadel (autorizações em `roles-ipm`) | Controller | Controller |

## 7. Verificação

Testes unitários, de contrato e de integração (contra o PostgreSQL de dev, com os papéis reais) cobrem a admissão, as regras, o Controller, o Publisher e o apagamento por conta removida. **Não verificado:** a suíte `tests/e2e` (ligar, listar, duplicar, desligar, religar e caos) contra a stack nova.
