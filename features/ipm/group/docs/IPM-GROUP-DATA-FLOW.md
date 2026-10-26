# ipm.group: fluxo de dados (do `POST` até o estado reconciliado)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/ipm/role/docs/IPM-ROLE-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose),
verificados pela suíte e2e (`tests/e2e`), inclusive com falha de componente. As decisões de desenho são a
[0086](../../../../.decisions/0086-banco-platform-plano-de-dados-fora-do-ssot.md) e a
[0088](../../../../.decisions/0088-ipm-group-grupos-de-usuarios-por-organizacao.md).

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, operador)
são fictícios.

**Comando.** `sk ipm group create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

Criar um Grupo (`POST /v1/ipm/groups {"organizationId": "0199c8a0-...", "name": "auditors", "description": "Auditores da Organization.", "roles": ["ipm.userViewer"]}`)
não grava nada no Zitadel: conforme a decisão 0088, **`ipm.group` existe no SSOT da Smarkee e no banco `platform`** como agrupador
de Roles compostas (`ipm.role`) escopado por Organization. Quando atribuído a um usuário (`ipm.user`), o Manager e o Reconciler
de `ipm/user` expandem os `groups` em Roles e permissões atômicas.

1. **Receiver** (`ipm-group-receiver`): autentica o JWT, exige a permissão da operação (`ipm.group.create|get|list|update|delete`
   ou `ipm.group.admin`), verifica a relação do solicitante com a Organization (`OPERATOR`, `OWNER` via Receiver de
   `ipm/organization` ou `MEMBER` via Receiver de `ipm/user`), valida as `roles` contra o catálogo dinâmico (`RolesCatalog`),
   exige `ipm.group.bind` para atribuir ou alterar `roles` quando o solicitante é membro, verifica a cota de grupos por
   Organization e, no `DELETE`, consulta o Receiver de `ipm/user` para bloquear a exclusão (`409 ResourcesAttached`) se houver
   usuários associados ao grupo. Publica `requested` no NATS e responde `202 Accepted` com `resourceId` e `operationId`.
2. **Manager** (`ipm-group-manager`): consome `REQUESTED`, valida `unique_value` (`(organizationId, name)` único entre grupos
   ativos sob trava consultiva), `owner_quota` e catálogo de `roles`, grava `ipm.group`, `ipm.group_operation` e `ipm.group_outbox`
   numa única transação no banco `ssot`.
3. **Publisher** (`ipm-group-publisher`): drena `ipm.group_outbox` em ordem de `sequence` e publica `desired` e `updated` no
   JetStream com `Nats-Msg-Id` determinístico.
4. **Observer** (`ipm-group-observer`): lê o estado materializado do grupo no banco `platform` (`ipm.group` e `ipm.group_role`,
   papel somente `SELECT`) e publica `observed` (`present`, `absent` ou `unknown`).
5. **Reconciler** (`ipm-group-reconciler`): compara `desired` e `observed` (`name`, `description`, `roles`,
   `deletionProtection`) e emite `action` (`create`, `update` ou `delete`) particionada por `resourceId`.
6. **Executor** (`ipm-group-executor`): revalida a `action` contra o `desired` vigente, aplica a mutação transacional em
   `ipm.group` e `ipm.group_role` no banco `platform` e publica `completed` ou `failed` em `RESULT`.
7. **Manager** (retorno): consome `OBSERVED` e `RESULT`, promove a fase para `Ready` quando `observed` converge com `desired` na
   geração atual e conclui a `Operation` (`completed`). Na remoção convergida (`absent`), apaga a linha do SSOT e publica
   `updated` com `removed: true`.

Arquitetura: [`architecture/01-componentes.svg`](architecture/01-componentes.svg). Modelo físico:
[`database/01-er-fisico.svg`](database/01-er-fisico.svg). Fluxo de criação:
[`flow/01-criar-group.svg`](flow/01-criar-group.svg).

## 1. Borda e Receiver (`ipm-group-receiver`)

### 1.1 Rotas e autorização (`receiver/http/app.py`)

| Método e rota | Permissão exigida | Escopo e regras adicionais |
|---|---|---|
| `POST /v1/ipm/groups` | `ipm.group.create` (ou `ipm.group.admin`) | `standing_in(organizationId)` deve ser `OPERATOR`, `OWNER` ou `MEMBER`; atribuir `roles` não vazias por `MEMBER` exige `ipm.group.bind`; respeita `group_quota` por Organization (exceto `OPERATOR`) |
| `GET /v1/ipm/groups/{group_id}` | `ipm.group.get` (ou `ipm.group.admin`) | Visível apenas para `OPERATOR`, `OWNER` ou `MEMBER` da Organization do grupo (senão `404 NotFound`) |
| `GET /v1/ipm/groups?organizationId=...` | `ipm.group.list` (ou `ipm.group.admin`) | Exige `organizationId`; paginação por `cursor` e `limit` sobre a view `ipm.group_v1` |
| `PATCH /v1/ipm/groups/{group_id}` | `ipm.group.update` (ou `ipm.group.admin`) | Exige `resourceVersion` atual (`409 Conflict` se divergir); alterar `roles` por `MEMBER` exige `ipm.group.bind`; alterar `reconciliation` é restrito a `OPERATOR` |
| `DELETE /v1/ipm/groups/{group_id}?resourceVersion=...` | `ipm.group.delete` (ou `ipm.group.admin`) | Exige `resourceVersion` atual; se `deletionProtection == true`, responde `409 DeletionProtected`; se houver usuários associados ao grupo na Organization (`count_users_with_group > 0`), responde `409 ResourcesAttached` |
| `GET /v1/ipm/groups/{group_id}/operations/{operation_id}` | Mesma visibilidade do grupo | Lê a view `ipm.group_operation_v1` |

Diagramas de validação e atualização/remoção: [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg) e
[`flow/03-atualizar-e-remover.svg`](flow/03-atualizar-e-remover.svg).

### 1.2 Exemplo de `requested-create` publicado em `REQUESTED`

Subject: `receiver.requested.ipm.group.0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e.create`

```json
{
  "messageId": "0199c8a4-7b20-7d11-8a10-112233445566",
  "schemaVersion": "1.0",
  "messageType": "requested",
  "emitter": "receiver",
  "module": "ipm",
  "resourceType": "group",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "create",
  "requestedBy": "326481904123456789",
  "correlationId": "0199c8a4-7b20-7d11-8a10-112233445566",
  "causationId": "0199c8a4-7b20-7d11-8a10-112233445566",
  "occurredAt": "2026-10-25T14:00:00Z",
  "publishedAt": "2026-10-25T14:00:00Z",
  "data": {
    "operationId": "0199c8a4-7b20-7d11-8a10-112233445566",
    "requestDigest": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "organizationQuotaLimit": 50,
    "specification": {
      "organizationId": "0199c8a0-0000-7000-8000-0000000000aa",
      "name": "auditors",
      "description": "Auditores da Organization.",
      "roles": ["ipm.userViewer"],
      "deletionProtection": false
    }
  }
}
```

## 2. Manager (`ipm-group-manager`)

### 2.1 Política (`manager/domain/group.py`)

| Operação | Condição verificada na transação | Desfecho |
|---|---|---|
| `create` | `roles` contém item fora do `RolesCatalog` | recusa `validation` |
| `create` | já existe Grupo presente na mesma `organizationId` com o mesmo `name` (trava consultiva `ipm.group.name:<organizationId>:<name>`) | recusa `conflict` |
| `create` | total de grupos presentes na `organizationId` atingiu `organizationQuotaLimit` | recusa `quota_exceeded` |
| `update` ou `delete` | Grupo inexistente ou já com `lifecycle = absent` | recusa `not_found` |
| `update` ou `delete` | `resourceVersion` diferente da atual | recusa `conflict` |
| `delete` | `deletionProtection` é `true` | recusa `protected` |
| qualquer | válido | aceita: grava `desired` com nova geração (`roles` deduplicadas e ordenadas; `deletionProtection: false` por padrão no `create`) |

### 2.2 Gravação (`manager/store/ssot.py`)

- **Criar aceito:** `INSERT` em `ipm.group` (`desired_generation = 1`, `resource_version = 1`, `phase = Pending`).
- **Atualizar aceito:** `UPDATE` em `ipm.group` (`desired_generation + 1`, `resource_version + 1`, `phase = Reconciling`).
- **Remover aceito:** `lifecycle = absent`, `phase = Deleting`.
- **Operation e Outbox:** `INSERT` em `ipm.group_operation` e, quando aceito, em `ipm.group_outbox`.

Diagrama de falhas no Manager e mensageria:
[`flow/04-falhas-no-manager-e-mensageria.svg`](flow/04-falhas-no-manager-e-mensageria.svg).

## 3. Outbox → NATS (`ipm-group-publisher`)

O Publisher lê `ipm.group_outbox` em ordem de `sequence`, valida o envelope, acrescenta `publishedAt` e `publishedBy` e publica em
`manager.desired.ipm.group.<resourceId>.changed` e `manager.updated.ipm.group.<resourceId>.changed`. Além do Reconciler, Observer e
Executor de `ipm.group`, o **Manager e o Reconciler de `ipm.user`** consomem `DESIRED` de `ipm.group` para atualizar o catálogo de
grupos em memória e reconciliar os usuários membros quando as `roles` de um grupo mudam (decisão 0088).

```json
{
  "messageType": "desired",
  "emitter": "manager",
  "module": "ipm",
  "resourceType": "group",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "publishedBy": "ipm-group-publisher",
  "data": {
    "organizationId": "0199c8a0-0000-7000-8000-0000000000aa",
    "name": "auditors",
    "description": "Auditores da Organization.",
    "roles": ["ipm.userViewer"],
    "deletionProtection": false,
    "lifecycle": "present",
    "reconciliation": "active"
  }
}
```

## 4. Observer (`ipm-group-observer`)

Lê `ipm.group` e `ipm.group_role` no banco `platform` usando o papel `ipm_group_observer_login` (somente `SELECT`) e publica em
`observer.observed.ipm.group.<resourceId>.changed`:

- `present`, com `name`, `description`, `roles` (ordenadas) e `deletionProtection`;
- `absent`, quando o registro não existe em `ipm.group` no banco `platform`;
- `unknown`, para qualquer erro de conexão ou consulta (nunca confundido com `absent`).

## 5. Reconciler (`ipm-group-reconciler`)

Reconstrói o estado a partir de `DESIRED`, `OBSERVED` e `RESULT` (`DeliverLastPerSubject`) e compara `lifecycle`, `name`,
`description`, `roles` e `deletionProtection`:

- `observed` ausente com `lifecycle = present` → `create` (`Missing`);
- qualquer campo divergente (`description`, `roles`, `deletionProtection`) → `update` (`Drift`);
- `lifecycle = absent` com o Grupo presente → `delete` (`DeletionRequested`).

A `action` sai em `reconciler.action.p<partição>.ipm.group.<resourceId>.<operação>` com `Nats-Msg-Id` igual ao `actionId`.
Diagrama: [`flow/05-falhas-na-reconciliacao.svg`](flow/05-falhas-na-reconciliacao.svg).

## 6. Executor (`ipm-group-executor`)

Revalida cada `action` contra o `desired` vigente e aplica no banco `platform` (schema `ipm`), com o papel
`ipm_group_executor_login`:

- **`create` / `update`:** em uma única transação, faz upsert em `ipm.group` (`resource_id`, `organization_id`, `name`,
  `description`, `deletion_protection`) e sincroniza `ipm.group_role`. Tentativa de alterar `name` ou `organizationId` é rejeitada
  com `Rejected` permanente.
- **`delete`:** remove a linha de `ipm.group` no banco `platform` (`ipm.group_role` é limpa por `ON DELETE CASCADE`; idempotente se
  já ausente).
- **Falha transitória de banco:** `ExternalError` com nova tentativa.

O resultado sai em `executor.completed|failed.ipm.group.<resourceId>.<operação>`. Diagrama:
[`flow/06-falhas-no-executor.svg`](flow/06-falhas-no-executor.svg).

## 7. Manager aplica `observed` e resultados

O Manager consome `OBSERVED` e `RESULT` (`ipm-group-manager-observed` e `-result`) e atualiza o SSOT:

- **`observed`:** grava `observed` e calcula a fase (`Ready` quando `name`, `description`, `roles` e `deletionProtection`
  convergem com o `desired` e `observed_generation == desired_generation`). Remoção convergida (`absent`) **apaga a linha** de
  `ipm.group` no SSOT e publica `updated` com `removed: true`.
- **Operation:** `Reconciling` marca operações aceitas como `in_progress`; `Ready` (ou remoção convergida) as conclui (`completed`).
- **Resultado:** registrado uma vez por `actionId` em `ipm.group_action_result`. No limite de falhas (5), `reconciliation` passa a
  `suspended` e a fase a `Failed`.

## 8. Estados

- **Fase** (`phase`): `Pending`, `Reconciling`, `Ready`, `Failed` e `Deleting`. Diagrama:
  [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg).
- **Operation:** `accepted`, `in_progress`, `completed` e `rejected`. Diagrama:
  [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ssot`: `ipm.group` | Manager | Receiver (view `ipm.group_v1`) |
| `ssot`: `ipm.group_operation` | Manager | Receiver (view `ipm.group_operation_v1`) |
| `ssot`: `ipm.group_action_result` | Manager | Manager (dedupe por `actionId`) |
| `ssot`: `ipm.group_outbox` | Manager (insere) | Publisher (lê e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer, Executor, `ipm.user` (Manager e Reconciler) |
| `OBSERVED` | Observer | Reconciler, Manager |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer, Manager |
| `platform`: `ipm.group` e `ipm.group_role` | Executor | Observer (somente `SELECT`) |

## 10. Verificação (2026-10-25, dev)

Com os seis componentes no Compose, a suíte unitária e de contrato (`285 passed`) e a suíte e2e (`tests/e2e`) validam a criação do
Grupo até `Ready`, atualização de `description` e `roles`, bloqueio por `deletionProtection`, desproteção e remoção completa (com
confirmação `absent` pelo Observer e remoção no SSOT pelo Manager), além da rejeição de nome duplicado na mesma Organization.
