# ipm.permission: fluxo de dados (do `POST` até a role de projeto no Zitadel)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/ipm/organization/docs/IPM-ORGANIZATION-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose),
verificados pela suíte e2e (`tests/e2e`) contra o Zitadel real, inclusive com falha de componente. A decisão de desenho é a
[0083](../../../../.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md).

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, operador)
são fictícios.

**Comando.** `sk ipm permission create|get|list|update|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

Criar uma Permission (`POST /v1/ipm/permissions {"key": "sum.service.audit", "displayName": "Audit Services", "grantableToOrganizations": true}`)
não cria nada no Zitadel diretamente. O pedido vira uma mensagem `requested`, o Manager decide e grava no SSOT, o Publisher
publica o `desired`, o Reconciler compara com o `observed` e manda uma `action`, o Executor escreve a role de projeto em
`roles-<módulo>` no Zitadel (`zitadel.project.v2.ProjectService`), e o Observer lê de volta.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/ipm/permissions` (via gateway) | `{key, displayName, description, grantableToOrganizations, deletionProtection}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `ipm.permission`, `ipm.permission_operation`, `ipm.permission_outbox` |
| 4 | Publisher → consumidores | NATS, Stream `DESIRED` | `desired` | `ipm.permission_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `ipm.permission` (observação), `ipm.permission_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → Zitadel; Executor → Manager | HTTP no Zitadel (`ProjectService`); NATS, Stream `RESULT` | `completed` | `ipm.permission_action_result`, `ipm.permission` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `ipm.permission` → `Ready`, `ipm.permission_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `ipm.permission_outbox` |

Só o **Manager** escreve no SSOT de `ipm.permission`. Receiver, Reconciler, Executor, Observer e Publisher não gravam nas
tabelas de recurso (o Publisher só marca `published_at` no outbox).

Diagramas: criar [`flow/01-criar-permission.svg`](flow/01-criar-permission.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), atualizar e remover [`03`](flow/03-atualizar-e-remover.svg), falhas no Manager e na
mensageria [`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação [`05`](flow/05-falhas-na-reconciliacao.svg) e no
Executor [`06`](flow/06-falhas-no-executor.svg). Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg).
Estados: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg).
Banco: [`database/01-er-fisico.svg`](database/01-er-fisico.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver | UUIDv7 minúsculo | Identidade da Permission no SSOT. No Zitadel, a permissão é identificada por `(projectId, roleKey)` onde `roleKey = key`. |
| `key` | Solicitante (imutável) | `<módulo>.<tipo>.<ação>` (`^(core\|sum\|ipm\|bsm)\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`) | Chave atômica da permissão no projeto `roles-<módulo>` do Zitadel. |
| `operationId`, `requestDigest` | Receiver | UUIDv7 (ou determinístico com `Idempotency-Key`); SHA-256 do pedido | Identidade da Operation; a repetição produz o mesmo valor. |
| `messageId` | Quem emite | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId`, `causationId` | Receiver; quem emite | UUIDv7; `messageId` da causa | Rastreiam o pedido do início ao fim e encadeiam causa e efeito. |
| `actionId` | Reconciler | `<resourceId>.<desiredGeneration>.<operação>.<messageId do observed>` | Identidade determinística da decisão; Executor e Manager a usam para ser idempotentes. |

## 1. CLI → Receiver: `POST /v1/ipm/permissions`

O corpo contém `key`, `displayName` e, opcionalmente, `description`, `grantableToOrganizations` (`true` por padrão) e
`deletionProtection` (`true` por padrão) (`schemas/ipm/permission/api-create-request`). O Receiver valida o token (audience
`roles-ipm`), exige a permissão `ipm.permission.create` (ou `ipm.permission.admin`) e **o e-mail verificado**, atribui o
`resourceId` e publica `requested` em `receiver.requested.ipm.permission.<resourceId>.create`, com `Nats-Msg-Id` igual ao
`operationId`:

```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01", "schemaVersion": "1.0", "messageType": "requested",
  "emitter": "receiver", "module": "ipm", "resourceType": "permission",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "create",
  "requestedBy": "0199c8a4-0000-7000-8000-00000000beef", "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "data": {
    "operationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f", "requestDigest": "60303ae2…c752",
    "specification": {
      "key": "sum.service.audit", "displayName": "Audit Services",
      "description": "Permite auditar serviços.", "grantableToOrganizations": true, "deletionProtection": true
    }
  }
}
```

As demais rotas: `GET` e a lista (acessíveis a quem tem `ipm.permission.get` ou `ipm.permission.list`, inclusive usuários das
organizações), `PATCH` (exige `ipm.permission.update` ou `ipm.permission.admin`; `reconciliation` só o operador com `admin`
altera), `DELETE?resourceVersion=` e `GET .../operations/{operationId}`. Erros no formato `api-error`: `400` entrada inválida,
`401`, `403` (sem a permissão ou e-mail não verificado), `404`, `409` versão desatualizada ou `DeletionProtected`, `422` reuso
da `Idempotency-Key`, `503` pedido não registrado (com `Retry-After`). Diagrama:
[`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg). O contrato descritivo é `openapi.json`.

## 2. Manager consome `requested` e grava

O consumer durável `ipm-permission-manager-requested` (pull, ACK explícito) entrega a mensagem ao handler:

1. valida o envelope e os dados; desvio do contrato, de módulo ou de versão `MAJOR` é `TERM`;
2. aplica tudo numa transação, com a linha bloqueada e trava consultiva por `key`;
3. ACK depois do `COMMIT`; falha transitória do banco é `RETRY` com atraso.

### 2.1 Decisão (domínio puro, `domain/permission.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar | `key` já usada por outra Permission presente | recusa `validation` |
| atualizar ou remover | Permission inexistente ou já removida | recusa `not_found` |
| atualizar ou remover | `resourceVersion` diferente da atual | recusa `conflict` |
| remover | `deletionProtection` diferente de `false` | recusa `protected` (decisão 0043); antes dela, o Receiver já responde `409 DeletionProtected` |
| qualquer | senão | aceita: `desired` com a nova geração (`lifecycle absent` ao remover) |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `ipm.permission` (geração 1, versão 1, fase `Pending`). A unicidade da `key` é conferida na mesma
  unidade atômica sob trava consultiva.
- **Atualizar aceito:** `UPDATE` da linha (geração + 1, versão + 1, fase `Reconciling`). **Remover aceito:** `lifecycle =
  absent`, fase `Deleting`.
- **Operation:** `INSERT` em `ipm.permission_operation` com `accepted` (com a geração) ou `rejected` (com o motivo, sem geração).
- **Outbox:** só nas aceitas, `INSERT` em `ipm.permission_outbox` com a mensagem `desired`.

Reentrega com o mesmo `operationId` não grava nada (`Duplicate`, e o ACK acontece).

## 3. Outbox → NATS

O Publisher (`ipm-permission-publisher`) lê as linhas pendentes em ordem de `sequence`, valida o envelope de forma estrita,
acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.ipm.permission.<resourceId>.changed`, com
`Nats-Msg-Id` igual ao `messageId`; marca `published_at` **depois** da confirmação do transporte. Além do Reconciler, Observer
e Executor da própria feature, o Reconciler e o Executor de `ipm.organization` também consomem `DESIRED` de `ipm.permission`
para atualizar dinamicamente os `ProjectGrants` das organizações (decisão 0083).

```json
{
  "messageType": "desired", "emitter": "manager", "module": "ipm", "resourceType": "permission",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "changed", "desiredGeneration": 1,
  "publishedBy": "ipm-permission-publisher",
  "data": {
    "key": "sum.service.audit", "displayName": "Audit Services", "description": "Permite auditar serviços.",
    "grantableToOrganizations": true, "deletionProtection": true,
    "lifecycle": "present", "reconciliation": "active"
  }
}
```

## 4. Observer (`ipm-permission-observer`)

Resolve o projeto `roles-<módulo>` no Zitadel a partir do prefixo de `key` (`core`, `sum`, `ipm` ou `bsm`) e consulta a role de
projeto pela API v2 (`zitadel.project.v2.ProjectService/ListProjectRoles`), com a conta `ipm-permission-observer`
(`ORG_OWNER_VIEWER` nas organizações `core` e `operator` e `PROJECT_OWNER_VIEWER` nos projetos `roles-<módulo>` e `roles-operator`; sem o papel de organização o Zitadel devolve a lista de roles vazia e a role é observada como ausente, decisão 0084), além dos metadados locais de
catálogo (`description`, `grantableToOrganizations`, `deletionProtection`). Produz:

- `present`, com `key`, `displayName`, `description`, `grantableToOrganizations`, `deletionProtection` e `group` (`<módulo>.<tipo>`);
- `absent`, **só** quando a consulta no Zitadel teve sucesso e a role não existe no projeto;
- `unknown`, para qualquer falha de leitura do Zitadel. Erro de leitura nunca vira `absent`.

## 5. Reconciler (`ipm-permission-reconciler`)

Reconstrói o estado da mensageria (`DeliverLastPerSubject`) e compara `lifecycle`, `key`, `displayName`, `description`,
`grantableToOrganizations` e `deletionProtection`:

- `observed` ausente com `lifecycle present` → `create` (`Missing`);
- qualquer campo gerenciado diferente do `desired` → `update` (`Drift`);
- `lifecycle absent` com a permissão presente → `delete` (`DeletionRequested`).

A `action` sai em `reconciler.action.ipm.permission.<resourceId>.<operação>` com `Nats-Msg-Id` igual ao `actionId`. Diagrama:
[`flow/05-falhas-na-reconciliacao.svg`](flow/05-falhas-na-reconciliacao.svg).

## 6. Executor (`ipm-permission-executor`)

Único componente que escreve as permissões atômicas nos projetos `roles-<módulo>` do Zitadel, com a conta
`ipm-permission-executor` (`ORG_PROJECT_PERMISSION_EDITOR` na organização `core` e `PROJECT_OWNER` nos projetos `roles-<módulo>`),
e persiste os metadados de catálogo em `<stateDir>/<resourceId>.json`.

- **`create`:** adiciona a role `key` no projeto `roles-<módulo>` (`AddProjectRole`, com `group = <módulo>.<tipo>` e
  `displayName`; `409 AlreadyExists` é tratado de forma idempotente) e grava os metadados locais.
- **`update`:** atualiza `displayName` e `group` no Zitadel (`UpdateProjectRole`, ou `AddProjectRole` se ausente) e atualiza os
  metadados locais.
- **`delete`:** remove a role do projeto no Zitadel (`RemoveProjectRole`, ignorando `404`) e apaga o arquivo de metadados.

O resultado sai em `executor.completed|failed.ipm.permission.<resourceId>.<operação>`. Diagrama:
[`flow/06-falhas-no-executor.svg`](flow/06-falhas-no-executor.svg).

## 7. Manager aplica `observed` e resultados

O Manager consome `OBSERVED` e `RESULT` (`ipm-permission-manager-observed` e `-result`) e aplica ao SSOT:

- **`observed`:** grava `observed` e calcula a fase (`Ready` quando `key`, `displayName`, `description`,
  `grantableToOrganizations` e `deletionProtection` convergem com o `desired` e `observedGeneration` confirma a geração atual).
  Remoção convergida (`absent`) **apaga a linha** e publica `updated` com `removed`.
- **Operation:** `Reconciling` marca as pendentes como `in_progress`; `Ready` (ou remoção convergida) as conclui (`completed`).
- **Resultado:** registrado uma vez por `actionId` (`ipm.permission_action_result`). No limite de falhas (5), `reconciliation`
  vira `suspended`.

## 8. Estados

- **Fase** (`phase`): `Pending`, `Reconciling`, `Ready`, `Failed` e `Deleting`. Diagrama:
  [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg).
- **Operation:** `accepted`, `in_progress`, `completed` e `rejected`. Diagrama:
  [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ipm.permission` | Manager | Receiver (view `ipm.permission_v1`) |
| `ipm.permission_operation` | Manager | Receiver (view `ipm.permission_operation_v1`) |
| `ipm.permission_action_result` | Manager | Manager (dedupe por `actionId`) |
| `ipm.permission_outbox` | Manager (insere) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer, Executor, `ipm.organization` (Reconciler/Executor) |
| `OBSERVED` | Observer | Reconciler, Manager, `ipm.organization` (Reconciler/Executor) |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer, Manager |
| Zitadel (`roles-<módulo>`) | Executor | Observer (leitura) |

## 10. Verificação (2026-10-24, dev)

Com os seis componentes no Compose e o Zitadel real, a suíte e2e (`tests/e2e`, `13 passed`) cria a permissão até `Ready`,
confere a criação no projeto `roles-sum` do Zitadel, atualiza `displayName`, desprotege e remove (o Observer confirma `absent`
e o Manager apaga a linha), e executa os 5 cenários de caos (`E2E_CHAOS=1`) derrubando Manager, Publisher, Reconciler, Observer
e Executor durante pedidos ativos.
