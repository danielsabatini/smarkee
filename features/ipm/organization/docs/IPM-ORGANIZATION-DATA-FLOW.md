# ipm.organization: fluxo de dados (do `POST` até a organização no Zitadel)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/core/account/docs/CORE-ACCOUNT-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose), verificados
pela suíte e2e (`tests/e2e`) contra o Zitadel real, inclusive com falha de componente. A decisão de desenho é a
[0038](../../../../.decisions/0038-organization-refeita-a-partir-do-user.md).

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, dono)
são fictícios.

**Comando.** `sk ipm organization create|get|list|update|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

Criar uma Organization (`POST /v1/ipm/organizations {"name": "acme"}`) não cria nada no Zitadel diretamente. O pedido vira
uma mensagem `requested`, o Manager decide e grava, o Publisher publica o `desired`, o Reconciler compara com o `observed` e
manda uma `action`, o Executor escreve a organização no Zitadel, e o Observer lê de volta.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/ipm/organizations` (via gateway) | `{name}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `ipm.organization`, `ipm.organization_operation`, `ipm.organization_outbox` |
| 4 | Publisher → consumidores | NATS, Stream `DESIRED` | `desired` | `ipm.organization_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `ipm.organization` (observação), `ipm.organization_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → Zitadel; Executor → Manager | HTTP no Zitadel; NATS, Stream `RESULT` | `completed` | `ipm.organization_action_result`, `ipm.organization` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `ipm.organization` → `Ready`, `ipm.organization_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `ipm.organization_outbox` |

Só o **Manager** escreve no SSOT de `ipm.organization`. Receiver, Reconciler, Executor, Observer e Publisher não gravam nas
tabelas de recurso (o Publisher só marca `published_at` no outbox).

Diagramas: criar [`flow/01-criar-organization.svg`](flow/01-criar-organization.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), atualizar e remover [`03`](flow/03-atualizar-e-remover.svg), falhas no Manager e na
mensageria [`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação [`05`](flow/05-falhas-na-reconciliacao.svg) e no
Executor [`06`](flow/06-falhas-no-executor.svg). Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg).
Estados: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg).
Banco: [`database/01-er-fisico.svg`](database/01-er-fisico.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver | UUIDv7 minúsculo | Identidade da Organization. Vira o ID da organização no Zitadel (`organization_id`), então repetir a criação não duplica. |
| `operationId`, `requestDigest` | Receiver | UUIDv7 (ou determinístico com `Idempotency-Key`); SHA-256 do pedido | Identidade da Operation; a repetição produz o mesmo valor. |
| `ownerAccountId` | Receiver | `sub` do token | O dono. Vem do token, nunca do corpo, e vive só no `desired`. |
| `messageId` | Quem emite | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId`, `causationId` | Receiver; quem emite | UUIDv7; `messageId` da causa | Rastreiam o pedido do início ao fim e encadeiam causa e efeito. |
| `actionId` | Reconciler | `<resourceId>.<desiredGeneration>.<operação>.<messageId do observed>` | Identidade determinística da decisão; Executor e Manager a usam para ser idempotentes. |

## 1. CLI → Receiver: `POST /v1/ipm/organizations`

O corpo é `{"name": "<nome>"}` (`schemas/ipm/organization/api-create-request`). O Receiver valida o token (audience
`roles-ipm`), exige a role `ipm.organization.create`, **o e-mail verificado** e a cota de Organizations por dono
(`IPM_ORGANIZATION_RECEIVER_API_ORGANIZATION_QUOTA`, padrão 1; o operador, com `ipm.organization.admin`, não tem cota), atribui o
`resourceId` e publica `requested` em `receiver.requested.ipm.organization.<resourceId>.create`, com `Nats-Msg-Id` igual ao
`operationId`:

```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01", "schemaVersion": "1.0", "messageType": "requested",
  "emitter": "receiver", "module": "ipm", "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "create",
  "requestedBy": "0199c8a4-0000-7000-8000-00000000beef", "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "data": {
    "operationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f", "requestDigest": "60303ae2…c752",
    "specification": {"name": "acme", "platformAccess": "granted"}, "ownerQuotaLimit": 1
  }
}
```

As demais rotas: `GET` e a lista (filtradas pelo dono; de outro dono é `404`, para não revelar que existe), `PATCH` (o dono
altera só o `name`; `platformAccess` e `reconciliation` são do operador), `DELETE?resourceVersion=` e
`GET .../operations/{operationId}`. Erros no formato `api-error`: `400` entrada inválida (sem repetir o valor enviado), `401`,
`403` (sem a role, e-mail não verificado, cota), `404`, `409` versão desatualizada, `422` reuso da `Idempotency-Key`, `503`
pedido não registrado (com `Retry-After`). Logo depois do `202`, a leitura pode dar `404` até o Manager gravar a Operation.
Diagrama: [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg). O contrato descritivo é `openapi.json`.

## 2. Manager consome `requested` e grava

O consumer durável `ipm-organization-manager-requested` (pull, ACK explícito) entrega a mensagem ao handler:

1. valida o envelope e os dados; desvio do contrato, de módulo ou de versão `MAJOR` é `TERM`;
2. aplica tudo numa transação, com a linha bloqueada e travas consultivas por nome e por dono;
3. ACK depois do `COMMIT`; falha transitória do banco é `RETRY` com atraso.

### 2.1 Decisão (domínio puro, `domain/organization.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar ou renomear | nome reservado (`core`, `smarkee`, `register`, `platform`, `system`, `admin`, `zitadel`) | recusa `validation` |
| criar ou renomear | nome já usado por outra Organization presente | recusa `validation` |
| criar | cota do dono esgotada (conferida de novo sob trava por dono; o Receiver só pré-checa) | recusa `validation` |
| atualizar ou remover | Organization inexistente ou já removida | recusa `not_found` |
| atualizar ou remover | `resourceVersion` diferente da atual | recusa `conflict` |
| remover | `deletionProtection` diferente de `false` (a Organization nasce protegida; registro sem o campo vale como protegido) | recusa `protected` (decisão 0043); antes dela, o Receiver já responde `409 DeletionProtected` |
| atualizar | só `deletionProtection` mudou (campo da plataforma, sem o que reconciliar) | conclui na hora: Operation `completed`, nova geração, a fase não muda |
| qualquer | senão | aceita: `desired` com a nova geração (`lifecycle absent` ao remover) |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `ipm.organization` (geração 1, versão 1, fase `Pending`). A unicidade do nome e a cota são
  conferidas na mesma unidade atômica, sob trava consultiva (nome e dono), porque os índices de busca não são únicos.
- **Atualizar aceito:** `UPDATE` da linha (geração + 1, versão + 1, fase `Reconciling`). **Remover aceito:** `lifecycle =
  absent`, fase `Deleting`.
- **Operation:** `INSERT` em `ipm.organization_operation` com `accepted` (com a geração) ou `rejected` (com o motivo, sem geração).
- **Outbox:** só nas aceitas, `INSERT` em `ipm.organization_outbox` com a mensagem `desired`.

Reentrega com o mesmo `operationId` não grava nada (`Duplicate`, e o ACK acontece).

## 3. Outbox → NATS

O Publisher (`ipm-organization-publisher`) lê as linhas pendentes em ordem de `sequence`, valida o envelope de forma estrita,
acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.ipm.organization.<resourceId>.changed`, com
`Nats-Msg-Id` igual ao `messageId`; marca `published_at` **depois** da confirmação do transporte. Só uma instância publica
por vez (trava consultiva de sessão). Envelope inválido ou recusa permanente mantêm a mensagem pendente, registram `ERROR` e
tiram o Publisher de `ready`, sem derrubar o processo (decisão 0018). O `desired` publicado:

```json
{
  "messageType": "desired", "emitter": "manager", "module": "ipm", "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "changed", "desiredGeneration": 1,
  "publishedBy": "ipm-organization-publisher",
  "data": {"name": "acme", "lifecycle": "present", "ownerAccountId": "0199c8a4-0000-7000-8000-00000000beef",
           "platformAccess": "granted", "reconciliation": "active"}
}
```

## 4. Observer (`ipm-organization-observer`)

Lê a organização no Zitadel, só de leitura, pela API v2 (`zitadel.org.v2.OrganizationService/ListOrganizations`, consulta pelo ID
exato), com a conta `ipm-organization-observer` (`IAM_OWNER_VIEWER`, de instância). Observa quando o `desired` chega, depois de
cada resultado e periodicamente (5 min, com jitter); com várias réplicas, cada uma observa só a sua partição. Produz:

- `present`, com `name`, `platformAccess` (`granted` com a organização ativa, `revoked` com ela desativada) e
  `organizationState` (`active` ou `inactive`);
- `absent`, **só** quando a consulta pelo ID teve sucesso e não trouxe resultado;
- `unknown`, para qualquer falha de leitura e para um estado que o contrato não conhece. Erro de leitura nunca vira `absent`.

```json
{"messageType": "observed", "emitter": "observer", "presence": "present", "observedAt": "2026-10-16T10:52:24Z",
 "causationId": "0199c8b3-4a00-7c2d-8e3f-4a5b6c7d8e06",
 "data": {"name": "acme", "platformAccess": "granted", "organizationState": "active"}}
```

## 5. Reconciler (`ipm-organization-reconciler`)

O estado é um cache descartável: cada instância cria os próprios consumers (`DeliverLastPerSubject`) e reconstrói o último
`desired`, `observed` e resultado de cada Organization ao iniciar. Antes de decidir, confere as guardas do loop: sem os dois
estados, `desired` suspenso, `observed` `unknown` ou vencido (mais estrito para `delete`), observação causada por um resultado
ainda não chegada, ação pendente da mesma geração e backoff após falha. Os campos comparados são `lifecycle`, `name` e
`platformAccess`:

- `observed` ausente com `lifecycle present` → `create` (`Missing`);
- `name` ou `platformAccess` diferentes do `desired` → `update` (`Drift`);
- `lifecycle absent` com a organização presente → `delete` (`DeletionRequested`).

A `action` sai em `reconciler.action.ipm.organization.<resourceId>.<operação>` (o Stream `ACTION` a particiona), com
`Nats-Msg-Id` igual ao `actionId`. Diagrama: [`flow/05-falhas-na-reconciliacao.svg`](flow/05-falhas-na-reconciliacao.svg).

## 6. Executor (`ipm-organization-executor`)

Único componente que escreve a Organization no Zitadel, com a conta `ipm-organization-executor` (`IAM_ORG_MANAGER`, de instância).
**Escreve só a organização**: não cria usuários, não autoriza o dono e não cria Project Grant (decisão 0038). Consome todas as
partições do `ACTION` (um consumer e um laço por partição, `max_ack_pending = 1`: uma ação por vez em cada recurso).

Antes de executar, cada `action` passa pela validação da mensagem (emissor `reconciler`, tipo, módulo, versão `MAJOR`,
`actionId`), pela idempotência (um `actionId` com desfecho registrado não é executado de novo; o resultado é republicado com o
mesmo `Nats-Msg-Id`) e pela **revalidação contra o `desired` vigente** (sem `desired` ou geração diferente é `failed`
`StaleAction`; `reconciliation` suspenso é `Suspended`; operação incoerente com o `lifecycle` é `Rejected`; todas permanentes).
Diagrama: [`flow/06-falhas-no-executor.svg`](flow/06-falhas-no-executor.svg). Depois, pela API v2 de organizações:

- **`create`:** cria a organização com o `resourceId` como ID e o `name`. Um `409` (ID ou nome já usados) leva a ler a organização
  pelo ID: se existe com o nome esperado, é sucesso idempotente; senão, `failed` `Rejected` (um nome já usado por outra organização do Zitadel que
  a plataforma não reservou). Depois deixa a organização ativa ou desativada conforme `platformAccess`.
- **`update`:** renomeia quando o nome difere e ativa (`granted`) ou desativa (`revoked`) quando o estado difere. Só chama o
  Zitadel quando há diferença; o "já feito" (nome igual, já ativa, já desativada) também é sucesso.
- **`delete`:** remove a organização; ausente também é sucesso (o Zitadel responde `200` a uma remoção repetida).

Erro transitório do Zitadel (indisponível, `429`, `5xx`) vira `failed` `ProviderUnavailable` com `retryable`, e o retry é do
Reconciler (com backoff). O resultado sai em `executor.completed|failed.ipm.organization.<resourceId>.<operação>`:

```json
{"messageType": "completed", "emitter": "executor", "operation": "create", "desiredGeneration": 1,
 "actionId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e.1.create.0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04", "data": {}}
```

## 7. Manager aplica `observed` e resultados

O Manager também consome `OBSERVED` e `RESULT` (`ipm-organization-manager-observed` e `-result`) e os aplica ao SSOT, cada mensagem
numa unidade atômica com a linha bloqueada:

- **`observed`:** ignorado se mais antigo que o último aplicado (`observedAt`). `unknown` só atualiza `presence` e `observed_at`.
  Senão grava `observed` e calcula a fase: `Ready` quando convergiu (`name` e `platformAccess` iguais aos do `desired`),
  `Reconciling` quando não, e `Deleting` com `lifecycle absent`. Remoção convergida (`absent`) **apaga a linha** e publica
  `updated` com `removed`.
- **Operation:** `Reconciling` marca as pendentes até a geração atual como `in_progress`; `Ready` as conclui (`completed`).
- **Resultado:** registrado uma vez por `actionId` (`ipm.organization_action_result`). Um `failed` marca a fase `Failed` da geração e
  soma `failure_count`; no limite (5) a `reconciliation` vira `suspended`, e o Reconciler para de decidir até um operador voltar
  para `active`.

## 8. Estados

- **Fase** (`phase`): `Pending` ao gravar, `Reconciling`, `Ready`, `Failed` (não terminal) e `Deleting`. Diagrama:
  [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg). `completed` não é `Ready`: só a observação compatível converge.
- **Operation:** `accepted`, `in_progress`, `completed` e `rejected` (com motivo, sem geração). Limitação: ela não vira `failed`; a
  falha aparece na fase `Failed` da Organization. Diagrama: [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ipm.organization` | Manager | Receiver (view `ipm.organization_v1`) |
| `ipm.organization_operation` | Manager | Receiver (view `ipm.organization_operation_v1`) |
| `ipm.organization_action_result` | Manager | Manager (dedupe por `actionId`) |
| `ipm.organization_outbox` | Manager (insere) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer, Executor (revalidação) |
| `OBSERVED` | Observer | Reconciler, Manager |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer, Manager |
| Zitadel (a organização) | Executor | Observer (leitura) |

## 10. Verificação (2026-10-16, dev)

Com os seis componentes no Compose e o Zitadel real, a suíte e2e (`tests/e2e`) cria a organização até `Ready`, renomeia,
desativa e reativa (`platformAccess`), remove (o Observer confirma `absent` e o Manager apaga a linha), e confere que nome
reservado e nome repetido nunca chegam ao Zitadel. Os testes de resiliência (`E2E_CHAOS=1`) derrubam o Manager, o Publisher, o
Reconciler, o Observer e o Executor durante um pedido: em todos os casos o loop converge. Cada Organization de teste é removida
pelo próprio loop ao final, sem deixar organização no Zitadel.
