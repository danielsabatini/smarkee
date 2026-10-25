# ipm.role: fluxo de dados (do `POST` até o estado reconciliado)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/ipm/organization/docs/IPM-ORGANIZATION-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose),
verificados pela suíte e2e (`tests/e2e`), inclusive com falha de componente. A decisão de desenho é a
[0083](../../../../.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md).

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, operador)
são fictícios.

**Comando.** `sk ipm role create|get|list|update|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

Criar uma Role (`POST /v1/ipm/roles {"key": "sum.serviceAuditor", "displayName": "SUM Service Auditor", "permissions": ["sum.service.get", "sum.service.list"]}`)
não grava nada no Zitadel: conforme a decisão 0083, **`ipm.role` existe 100% no SSOT da Smarkee** como agrupador de permissões
atômicas, e o Manager do `ipm/user` expande as `roles` em permissões atômicas antes de o Executor do `ipm/user` gravar o
`UserGrant` no Zitadel. O pedido vira uma mensagem `requested`, o Manager decide e grava no SSOT, o Publisher publica o
`desired`, o Reconciler compara com o `observed` e manda uma `action`, o Executor grava atomicamente o estado local em disco
(`<stateDir>/<resourceId>.json`), e o Observer lê de volta.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/ipm/roles` (via gateway) | `{key, displayName, description, permissions, deletionProtection}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `ipm.role`, `ipm.role_operation`, `ipm.role_outbox` |
| 4 | Publisher → consumidores | NATS, Stream `DESIRED` | `desired` | `ipm.role_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `ipm.role` (observação), `ipm.role_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → disco; Executor → Manager | I/O atômico em `<stateDir>/<resourceId>.json`; NATS, Stream `RESULT` | `completed` | `ipm.role_action_result`, `ipm.role` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `ipm.role` → `Ready`, `ipm.role_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `ipm.role_outbox` |

Só o **Manager** escreve no SSOT de `ipm.role`. Receiver, Reconciler, Executor, Observer e Publisher não gravam nas tabelas de
recurso (o Publisher só marca `published_at` no outbox).

Diagramas: criar [`flow/01-criar-role.svg`](flow/01-criar-role.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), atualizar e remover [`03`](flow/03-atualizar-e-remover.svg), falhas no Manager e na
mensageria [`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação [`05`](flow/05-falhas-na-reconciliacao.svg) e no
Executor [`06`](flow/06-falhas-no-executor.svg). Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg).
Estados: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg).
Banco: [`database/01-er-fisico.svg`](database/01-er-fisico.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver | UUIDv7 minúsculo | Identidade da Role no SSOT e nome do arquivo `<stateDir>/<resourceId>.json`. |
| `key` | Solicitante (imutável) | `<módulo>.<nomeRole>` (`^(core\|sum\|ipm\|bsm)\.[a-z][a-zA-Z0-9_]*$`, ex.: `ipm.userAdmin`, `bsm.accountViewer`) | Identificador semântico referenciado pelos recursos `ipm.user` no campo `roles`. |
| `operationId`, `requestDigest` | Receiver | UUIDv7 (ou determinístico com `Idempotency-Key`); SHA-256 do pedido | Identidade da Operation; a repetição produz o mesmo valor. |
| `messageId` | Quem emite | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId`, `causationId` | Receiver; quem emite | UUIDv7; `messageId` da causa | Rastreiam o pedido do início ao fim e encadeiam causa e efeito. |
| `actionId` | Reconciler | `<resourceId>.<desiredGeneration>.<operação>.<messageId do observed>` | Identidade determinística da decisão; Executor e Manager a usam para ser idempotentes. |

## 1. CLI → Receiver: `POST /v1/ipm/roles`

O corpo contém `key`, `displayName`, `permissions` (1 a 100 chaves de permissões atômicas únicas) e, opcionalmente,
`description` e `deletionProtection` (`true` por padrão) (`schemas/ipm/role/api-create-request`). O Receiver valida o token
(audience `roles-ipm`), exige a permissão `ipm.role.create` (ou `ipm.role.admin`) e **o e-mail verificado**, atribui o
`resourceId` e publica `requested` em `receiver.requested.ipm.role.<resourceId>.create`, com `Nats-Msg-Id` igual ao
`operationId`:

```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01", "schemaVersion": "1.0", "messageType": "requested",
  "emitter": "receiver", "module": "ipm", "resourceType": "role",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "create",
  "requestedBy": "0199c8a4-0000-7000-8000-00000000beef", "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "data": {
    "operationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f", "requestDigest": "60303ae2…c752",
    "specification": {
      "key": "sum.serviceAuditor", "displayName": "SUM Service Auditor",
      "description": "Leitura de serviços.", "permissions": ["sum.service.get", "sum.service.list"],
      "deletionProtection": true
    }
  }
}
```

As demais rotas: `GET` e a lista (acessíveis a quem tem `ipm.role.get` ou `ipm.role.list`, inclusive usuários das organizações),
`PATCH` (exige `ipm.role.update` ou `ipm.role.admin`; `reconciliation` só o operador com `admin` altera),
`DELETE?resourceVersion=` e `GET .../operations/{operationId}`. Erros no formato `api-error`: `400` entrada inválida, `401`,
`403` (sem a permissão ou e-mail não verificado), `404`, `409` versão desatualizada ou `DeletionProtected`, `422` reuso da
`Idempotency-Key`, `503` pedido não registrado (com `Retry-After`). Diagrama:
[`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg). O contrato descritivo é `openapi.json`.

## 2. Manager consome `requested` e grava

O consumer durável `ipm-role-manager-requested` (pull, ACK explícito) entrega a mensagem ao handler:

1. valida o envelope e os dados; desvio do contrato, de módulo ou de versão `MAJOR` é `TERM`;
2. aplica tudo numa transação, com a linha bloqueada e trava consultiva por `key`;
3. ACK depois do `COMMIT`; falha transitória do banco é `RETRY` com atraso.

### 2.1 Decisão (domínio puro, `domain/role.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar | `key` já usada por outra Role presente | recusa `validation` |
| criar ou atualizar | lista `permissions` vazia | recusa `validation` |
| atualizar ou remover | Role inexistente ou já removida | recusa `not_found` |
| atualizar ou remover | `resourceVersion` diferente da atual | recusa `conflict` |
| remover | `deletionProtection` diferente de `false` | recusa `protected` (decisão 0043); antes dela, o Receiver já responde `409 DeletionProtected` |
| qualquer | senão | aceita: `desired` com a nova geração (`lifecycle absent` ao remover) e `permissions` deduplicadas e ordenadas |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `ipm.role` (geração 1, versão 1, fase `Pending`). A unicidade da `key` é conferida na mesma
  unidade atômica sob trava consultiva.
- **Atualizar aceito:** `UPDATE` da linha (geração + 1, versão + 1, fase `Reconciling`). **Remover aceito:** `lifecycle =
  absent`, fase `Deleting`.
- **Operation:** `INSERT` em `ipm.role_operation` com `accepted` (com a geração) ou `rejected` (com o motivo, sem geração).
- **Outbox:** só nas aceitas, `INSERT` em `ipm.role_outbox` com a mensagem `desired`.

Reentrega com o mesmo `operationId` não grava nada (`Duplicate`, e o ACK acontece).

## 3. Outbox → NATS

O Publisher (`ipm-role-publisher`) lê as linhas pendentes em ordem de `sequence`, valida o envelope de forma estrita, acrescenta
`publishedAt` e `publishedBy` e publica em `manager.desired.ipm.role.<resourceId>.changed`, com `Nats-Msg-Id` igual ao
`messageId`; marca `published_at` **depois** da confirmação do transporte. Além do Reconciler, Observer e Executor da própria
feature, o **Manager de `ipm.user`** consome `DESIRED` de `ipm.role` para manter seu catálogo em memória e recalcular
automaticamente as permissões atômicas dos usuários que referenciam a role alterada (decisão 0083).

```json
{
  "messageType": "desired", "emitter": "manager", "module": "ipm", "resourceType": "role",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "changed", "desiredGeneration": 1,
  "publishedBy": "ipm-role-publisher",
  "data": {
    "key": "sum.serviceAuditor", "displayName": "SUM Service Auditor", "description": "Leitura de serviços.",
    "permissions": ["sum.service.get", "sum.service.list"], "deletionProtection": true,
    "lifecycle": "present", "reconciliation": "active"
  }
}
```

## 4. Observer (`ipm-role-observer`)

Lê `<stateDir>/<resourceId>.json` em modo somente leitura e produz:

- `present`, com `key`, `displayName`, `description`, `permissions` e `deletionProtection`;
- `absent`, quando o arquivo não existe;
- `unknown`, para qualquer falha de leitura ou JSON fora do contrato. Erro de leitura nunca vira `absent`.

## 5. Reconciler (`ipm-role-reconciler`)

Reconstrói o estado da mensageria (`DeliverLastPerSubject`) e compara `lifecycle`, `key`, `displayName`, `description`,
`permissions` e `deletionProtection`:

- `observed` ausente com `lifecycle present` → `create` (`Missing`);
- qualquer campo gerenciado diferente do `desired` → `update` (`Drift`);
- `lifecycle absent` com a Role presente → `delete` (`DeletionRequested`).

A `action` sai em `reconciler.action.ipm.role.<resourceId>.<operação>` com `Nats-Msg-Id` igual ao `actionId`. Diagrama:
[`flow/05-falhas-na-reconciliacao.svg`](flow/05-falhas-na-reconciliacao.svg).

## 6. Executor (`ipm-role-executor`)

Valida e revalida cada `action` contra o `desired` vigente e aplica no diretório local (`ipm-role-state`):

- **`create` / `update`:** grava `<stateDir>/<resourceId>.json` atomicamente via arquivo temporário no mesmo diretório e
  `os.replace`.
- **`delete`:** remove `<stateDir>/<resourceId>.json` (idempotente se já ausente).

O resultado sai em `executor.completed|failed.ipm.role.<resourceId>.<operação>`. Diagrama:
[`flow/06-falhas-no-executor.svg`](flow/06-falhas-no-executor.svg).

## 7. Manager aplica `observed` e resultados

O Manager consome `OBSERVED` e `RESULT` (`ipm-role-manager-observed` e `-result`) e aplica ao SSOT:

- **`observed`:** grava `observed` e calcula a fase (`Ready` quando `key`, `displayName`, `description`, `permissions` e
  `deletionProtection` convergem com o `desired` e `observedGeneration` confirma a geração atual). Remoção convergida (`absent`)
  **apaga a linha** e publica `updated` com `removed`.
- **Operation:** `Reconciling` marca as pendentes como `in_progress`; `Ready` (ou remoção convergida) as conclui (`completed`).
- **Resultado:** registrado uma vez por `actionId` (`ipm.role_action_result`). No limite de falhas (5), `reconciliation` vira
  `suspended`.

## 8. Estados

- **Fase** (`phase`): `Pending`, `Reconciling`, `Ready`, `Failed` e `Deleting`. Diagrama:
  [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg).
- **Operation:** `accepted`, `in_progress`, `completed` e `rejected`. Diagrama:
  [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ipm.role` | Manager | Receiver (view `ipm.role_v1`) |
| `ipm.role_operation` | Manager | Receiver (view `ipm.role_operation_v1`) |
| `ipm.role_action_result` | Manager | Manager (dedupe por `actionId`) |
| `ipm.role_outbox` | Manager (insere) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer, Executor, `ipm.user` (Manager) |
| `OBSERVED` | Observer | Reconciler, Manager |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer, Manager |
| `<stateDir>/<resourceId>.json` | Executor | Observer (leitura) |

## 10. Verificação (2026-10-24, dev)

Com os seis componentes no Compose, a suíte e2e (`tests/e2e`, `13 passed`) cria a role até `Ready`, atualiza `displayName` e
`permissions`, desprotege e remove (o Observer confirma `absent` e o Manager apaga a linha), e executa os 5 cenários de caos
(`E2E_CHAOS=1`) derrubando Manager, Publisher, Reconciler, Observer e Executor durante pedidos ativos.
