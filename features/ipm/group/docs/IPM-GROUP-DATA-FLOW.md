# ipm.group: fluxo de dados (do `POST` até o estado convergido)

Documento de fluxo de dados da feature `ipm.group`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0088](../../../../.decisions/0088-ipm-group-grupos-de-usuarios-por-organizacao.md): agrupador de papéis compostos (`ipm.role`) escopado por Organization;
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0099](../../../../.decisions/0099-extincao-do-banco-platform.md): extinção do banco `platform` e concentração no SSOT;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento total de chamadas HTTP mútuas entre features via Informers e projeções em memória no stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk ipm group create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

O Grupo existe **exclusivamente no SSOT da Smarkee** (banco `ssot`, schema `ipm`). Por se tratar de um recurso do perfil **`internal-state`**, ele não possui representação direta em provedores externos (como o Zitadel) nem no extinto banco `platform`: nasce imediatamente com `phase: Ready`, `presence: present` e `observedGeneration = generation`.

O pedido é admitido de forma síncrona pela API (`ipm-group-api`) em uma única transação no PostgreSQL. O Publisher (`ipm-group-publisher`) lê o outbox e publica o evento no stream `DESIRED` do NATS JetStream para que o Controller de `ipm.user` expanda os grupos em roles e permissões atômicas para os usuários membros.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/ipm/groups` (via gateway) | `{organizationId, name, description, roles, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Ready`) | `ipm.group`, `ipm.group_outbox`, `ipm.group_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`desired.ipm.group.<id>`) | `ipm.group_outbox.published_at` |
| 4 | NATS → Consumidor | JetStream (Informer/Stream) | `desired` entregue a `ipm.user` | Atualização de caches e reconciliação de usuários |

Apenas a **API** escreve nas tabelas de recurso (`ipm.group`) e outbox (`ipm.group_outbox`). O **Publisher** apenas lê o outbox e marca `published_at`. Não há `Receiver`, `Manager`, `Reconciler`, `Observer`, `Executor`, `Operation` nem banco `platform`.

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos de execução: criação [`flow/01-criar-group.svg`](flow/01-criar-group.svg), validação e borda [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), atualização e remoção [`flow/03-atualizar-e-remover.svg`](flow/03-atualizar-e-remover.svg), falhas e resiliência [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária do Grupo no SSOT. |
| `organizationId` | Solicitante (imutável) | UUIDv7 minúsculo | Escopo organizacional ao qual o Grupo pertence. |
| `name` | Solicitante | string até 64 chars | Nome do grupo (único dentro da mesma organização). |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/ipm/groups`

Exemplo de chamada via CLI:
```bash
sk ipm group create \
  --org 0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e \
  --name "auditors" \
  --description "Auditores da organização." \
  --roles "sum.serviceViewer,bsm.accountViewer"
```

A requisição chega ao gateway APISIX e é roteada para a API `ipm-group-api` na rota `POST /v1/ipm/groups`.

### 1.1 Autenticação, Escopo e Autorização na API
1. **Autenticação:** validação do token JWT OIDC emitido pelo Zitadel (audience `roles-ipm`).
2. **Escopo da Organization (sem chamadas HTTP entre features, decisão 0100):**
   - O solicitante pode ser:
     - **Operador global:** permissão `ipm.group.admin`;
     - **Dono da Organization (`ownerAccountId`):** identificado pela projeção em memória do stream `DESIRED` de `ipm.organization`;
     - **Membro da Organization:** identificado pelo claim `urn:zitadel:iam:org:project:<projectId>:roles` escopado ao domínio da Organization.
3. **Autorização:**
   - Exige `ipm.group.create` ou `ipm.group.admin`.
   - Quando o solicitante for um membro comum atribuindo ou modificando `roles`, exige também a permissão `ipm.group.bind` (Ajuste de segurança S0).
   - E-mail do solicitante deve estar verificado (`email_verified: true`).

### 1.2 Validações de Domínio e Admissão Síncrona
A API valida em memória antes de tocar no banco:
- Validação das roles solicitadas contra o catálogo de roles ativas (`CatalogConsumer` do stream `DESIRED` de `ipm.role`). Roles inexistentes retornam `400 ValidationFailed` com detalhe `UnknownRole`.
- Cota de grupos por organização: máximo de 50 grupos por organização (`QuotaExceeded` -> `409 Conflict`).
- Suporte a `Idempotency-Key`: repetição exata devolve `201 Created` do recurso já salvo; divergência de payload devolve `422 IdempotencyConflict`.

### 1.3 Gravação Atômica no SSOT
A admissão executa uma única transação SQL no banco `ssot`:
1. Trava consultiva por `(organization_id, name)` para garantir unicidade estrita do nome na organização.
2. `INSERT` na tabela `ipm.group`:
   - `phase = 'Ready'`
   - `presence = 'present'`
   - `desired_generation = 1`
   - `observed_generation = 1`
   - `desired = observed = {"organizationId": ..., "name": ..., "roles": [...], ...}`
   - `requested_by = <sub do solicitante>`
   - `correlation_id = <correlationId>`
3. `INSERT` na tabela `ipm.group_outbox`:
   - evento `desired.changed` contendo o envelope estrito do grupo.
4. `INSERT` na tabela `ipm.group_idempotency` (se `Idempotency-Key` foi enviada).

A API responde imediatamente `201 Created` contendo o `Resource` completo já convergido.

---

## 2. Publicação Assíncrona: `ipm-group-publisher`

O processo `ipm-group-publisher` roda de forma contínua e assíncrona:
1. Drena as linhas de `ipm.group_outbox` onde `published_at IS NULL` ordenadas por `sequence ASC`.
2. Constrói a mensagem NATS com cabeçalho `Nats-Msg-Id = message_id`.
3. Publica no subject `desired.ipm.group.<resourceId>` no JetStream (Stream `DESIRED`).
4. Ao receber o `PubAck` do JetStream, atualiza `UPDATE ipm.group_outbox SET published_at = now() WHERE sequence = ...`.

Envelope publicado:
```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e99",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "api",
  "module": "ipm",
  "resourceType": "group",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99",
  "operation": "changed",
  "desiredGeneration": 1,
  "publishedAt": "2026-10-28T14:00:00.000Z",
  "publishedBy": "ipm-group-publisher",
  "data": {
    "organizationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "name": "auditors",
    "description": "Auditores da organização.",
    "roles": ["sum.serviceViewer", "bsm.accountViewer"],
    "deletionProtection": true,
    "lifecycle": "present",
    "reconciliation": "active"
  }
}
```

---

## 3. Consumo pelo Controller de `ipm.user`

O **Controller de `ipm.user`** consome os eventos do subject `desired.ipm.group.>` no Stream `DESIRED`:
- Mantém em cache local todos os grupos e suas respectivas roles.
- Quando um usuário referencia um grupo em seu array `groups`, o Controller de usuário expande os grupos em roles e, recursivamente, as roles em permissões atômicas.
- Qualquer alteração na composição de roles de um grupo dispara a fila de reconciliação dos usuários daquela organização no Zitadel, sem nenhuma chamada HTTP síncrona entre as APIs.

---

## 4. Atualização e Exclusão

### 4.1 Atualização (`PATCH /v1/ipm/groups/{resourceId}`)
- Exige `ipm.group.update` ou `ipm.group.admin`.
- Membros alterando `roles` necessitam de `ipm.group.bind`.
- Concorrência otimista via `If-Match` ou `resourceVersion`.
- Na transação da API:
  - `desired_generation` é incrementado;
  - `observed_generation` acompanha o novo valor;
  - `resource_version` é incrementado;
  - novo evento `desired.changed` é inserido no outbox.
- Resposta síncrona `200 OK` com o recurso atualizado.

### 4.2 Exclusão (`DELETE /v1/ipm/groups/{resourceId}`)
- Exige `ipm.group.delete` ou `ipm.group.admin`.
- Se `deletionProtection` estiver ativa (`true`), recusa com `409 Conflict` (`DeletionProtected`).
- **Verificação de dependentes ativos (Ajuste 1 e decisão 0100):** a API consulta o cache local `UserUsageProjection` (Informer de `ipm.user`). Se houver usuários pertencentes ao grupo, a exclusão é recusada sincronamente com `409 Conflict` (`ResourcesAttached`), informando a quantidade de usuários dependentes.
- Quando elegível:
  - Remove a linha física em `ipm.group`.
  - Insere evento tombstone (`lifecycle: absent`) no `ipm.group_outbox`.
- Resposta síncrona `202 Accepted` (ou `204 No Content`). O Publisher propaga o tombstone e o Controller de `ipm.user` limpa a referência em seu cache.

---

## 5. Mapa de Acesso ao Banco de Dados

Todas as operações ocorrem exclusivamente no banco `ssot` sob o schema `ipm`:

| Tabela / Objeto | Papel `ipm_group_api` | Papel `ipm_group_publisher` |
|---|---|---|
| `ipm.group` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | Nenhum acesso |
| `ipm.group_v1` (view) | `SELECT` | Nenhum acesso |
| `ipm.group_outbox` | `INSERT` | `SELECT`, `UPDATE (published_at)` |
| `ipm.group_idempotency` | `SELECT`, `INSERT` | Nenhum acesso |

O banco `platform` foi extinto (decisão 0099) e não é acessado por nenhum processo.
