# ipm.role: fluxo de dados (do `POST` até o estado convergido)

Documento de fluxo de dados da feature `ipm.role`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0083](../../../../.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md): `ipm.role` como catálogo desacoplado no SSOT;
- [0092](../../../../.decisions/0092-ipm-roles-customizadas-por-organizacao.md): suporte a roles customizadas por organização;
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0099](../../../../.decisions/0099-extincao-do-banco-platform.md): extinção do banco `platform` e concentração no SSOT;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento HTTP via projeções e Informers no stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk ipm role create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

A Role composta vive **exclusivamente no SSOT da Smarkee** (banco `ssot`, schema `ipm`). Por se tratar de um recurso do perfil **`internal-state`**, ele não possui representação direta em provedores externos (como o Zitadel) nem no extinto banco `platform`: nasce imediatamente com `phase: Ready`, `presence: present` e `observedGeneration = generation`.

O pedido é admitido de forma síncrona pela API (`ipm-role-api`) em uma única transação no PostgreSQL. O Publisher (`ipm-role-publisher`) lê o outbox e publica o evento no stream `DESIRED` do NATS JetStream para notificar os consumidores externos (`ipm.user` e `ipm.group`).

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/ipm/roles` (via gateway) | `{key, displayName, permissions, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Ready`) | `ipm.role`, `ipm.role_outbox`, `ipm.role_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`desired.ipm.role.<id>`) | `ipm.role_outbox.published_at` |
| 4 | NATS → Consumidores | JetStream (Informer/Stream) | `desired` entregue a `ipm.user` e `ipm.group` | Atualização de caches e projeções em memória |

Apenas a **API** escreve nas tabelas de recurso (`ipm.role`) e outbox (`ipm.role_outbox`). O **Publisher** apenas lê o outbox e marca `published_at`. Não há `Receiver`, `Manager`, `Reconciler`, `Observer`, `Executor`, `Operation` nem banco `platform`.

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos de execução: criação [`flow/01-criar-role.svg`](flow/01-criar-role.svg), validação e borda [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), atualização e remoção [`flow/03-atualizar-e-remover.svg`](flow/03-atualizar-e-remover.svg), falhas e resiliência [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária da Role no SSOT. |
| `key` | Solicitante (imutável) | `<módulo>.<nomeRole>` ou `org.<nomeRole>` | Chave semântica referenciada por `ipm.user` e `ipm.group`. |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/ipm/roles`

Exemplo de chamada via CLI:
```bash
sk ipm role create \
  --key custom.supportAuditor \
  --name "Support Auditor" \
  --description "Leitura de auditoria e suporte." \
  --permissions "sum.service.get,sum.service.list"
```

A requisição chega ao gateway APISIX e é roteada para a API `ipm-role-api` na rota `POST /v1/ipm/roles`.

### 1.1 Autenticação e Autorização na API
1. **Autenticação:** validação do token JWT OIDC emitido pelo Zitadel (audience `roles-ipm`).
2. **Autorização:**
   - Para roles predefinidas da plataforma (`predefined`, organização `core`): exige permissão `ipm.role.admin`.
   - Para roles customizadas de organização (`custom`): exige `ipm.role.create` ou `ipm.role.admin` e pertinência à organização solicitada.
   - E-mail do solicitante deve estar verificado (`email_verified: true`).

### 1.2 Validações de Domínio e Admissão Síncrona
A API valida em memória antes de tocar no banco:
- Formato e unicidade da lista de permissões atômicas (`permissions`).
- Validação contra o catálogo de permissões conhecidas via `CatalogConsumer` (Informer do stream `DESIRED` de `ipm.permission`). Permissões desconhecidas resultam em `400 ValidationFailed` com detalhe `UnknownPermission`.
- Cota de roles customizadas: máximo de 10 por organização (`QuotaExceeded` -> `409 Conflict`).
- Suporte a `Idempotency-Key`: se enviada, a API checa `ipm.role_idempotency`. Se for repetição exata, devolve o recurso gravado (`201 Created`). Se houver divergência no payload, recusa com `422 IdempotencyConflict`.

### 1.3 Gravação Atômica no SSOT
A admissão executa uma única transação SQL no banco `ssot`:
1. Trava consultiva por `(organization_id, key)` para evitar corrida de duplicidade.
2. `INSERT` na tabela `ipm.role`:
   - `phase = 'Ready'`
   - `presence = 'present'`
   - `desired_generation = 1`
   - `observed_generation = 1`
   - `desired = observed = {"key": ..., "permissions": [...], ...}`
   - `requested_by = <sub do solicitante>`
   - `correlation_id = <correlationId>`
3. `INSERT` na tabela `ipm.role_outbox`:
   - evento `desired.changed` contendo o envelope estrito da role.
4. `INSERT` na tabela `ipm.role_idempotency` (se `Idempotency-Key` foi enviada).

A API responde imediatamente `201 Created` contendo o `Resource` completo já convergido.

---

## 2. Publicação Assíncrona: `ipm-role-publisher`

O processo `ipm-role-publisher` roda de forma contínua e assíncrona:
1. Drena as linhas de `ipm.role_outbox` onde `published_at IS NULL` ordenadas por `sequence ASC`.
2. Constrói a mensagem NATS com cabeçalho `Nats-Msg-Id = message_id` (para deduplicação automática no broker).
3. Publica no subject `desired.ipm.role.<resourceId>` no JetStream (Stream `DESIRED`).
4. Ao receber o `PubAck` do JetStream, atualiza `UPDATE ipm.role_outbox SET published_at = now() WHERE sequence = ...`.

Envelope publicado:
```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "publisher",
  "module": "ipm",
  "resourceType": "role",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "publishedAt": "2026-10-28T14:00:00.000Z",
  "publishedBy": "ipm-role-publisher",
  "data": {
    "key": "custom.supportAuditor",
    "displayName": "Support Auditor",
    "description": "Leitura de auditoria e suporte.",
    "permissions": ["sum.service.get", "sum.service.list"],
    "deletionProtection": true,
    "lifecycle": "present",
    "reconciliation": "active"
  }
}
```

---

## 3. Consumo e Desacoplamento entre Features

As mensagens publicadas no Stream `DESIRED` alimentam:
1. **`ipm.user` (Controller):** mantém em memória o mapa de todas as roles vigentes. Quando um usuário possui atribuição a uma role, o Controller de usuário expande as permissões atômicas em tempo de reconciliação com o Zitadel sem fazer chamadas HTTP à API de role.
2. **`ipm.group` (API):** consome as roles desejadas para validar o catálogo dinâmico de roles permitidas em grupos.
3. **`ipm.role` (API - projeções locais):** consome projeções de `ipm.user` e `ipm.group` (`RoleUsageProjection`) para saber se uma role está em uso.

---

## 4. Atualização e Exclusão

### 4.1 Atualização (`PATCH /v1/ipm/roles/{resourceId}`)
- Exige `ipm.role.update` ou `ipm.role.admin`.
- Controle de concorrência otimista via cabeçalho `If-Match` ou campo `resourceVersion`.
- Roles pré-definidas da plataforma (`roleType == predefined`) são imutáveis e retornam `403 Forbidden` (`PredefinedRoleProtected`).
- Na transação da API:
  - `desired_generation` é incrementado;
  - `observed_generation` acompanha o novo valor;
  - `resource_version` é incrementado;
  - novo evento `desired.changed` é inserido no outbox.
- Resposta síncrona `200 OK` com o recurso atualizado.

### 4.2 Exclusão (`DELETE /v1/ipm/roles/{resourceId}`)
- Exige `ipm.role.delete` ou `ipm.role.admin`.
- Roles pré-definidas não podem ser excluídas (`403 Forbidden`).
- Se `deletionProtection` estiver ativa (`true`), recusa com `409 Conflict` (`DeletionProtected`).
- **Verificação de dependentes ativos (Ajuste 1 e decisão 0100):** a API consulta o cache local `RoleUsageProjection`. Se houver usuários ou grupos referenciando a role, a exclusão é recusada sincronamente com `409 Conflict` (`ResourcesAttached`), listando a contagem de dependentes.
- Quando elegível:
  - Remove a linha física em `ipm.role`.
  - Insere evento tombstone (`lifecycle: absent`) no `ipm.role_outbox`.
- Resposta síncrona `202 Accepted` (ou `204 No Content`). O Publisher propaga o tombstone para que os consumidores limpem suas referências em cache.

---

## 5. Mapa de Acesso ao Banco de Dados

Todas as operações ocorrem exclusivamente no banco `ssot` sob o schema `ipm`:

| Tabela / Objeto | Papel `ipm_role_api` | Papel `ipm_role_publisher` |
|---|---|---|
| `ipm.role` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | Nenhum acesso |
| `ipm.role_v1` (view) | `SELECT` | Nenhum acesso |
| `ipm.role_outbox` | `INSERT` | `SELECT`, `UPDATE (published_at)` |
| `ipm.role_idempotency` | `SELECT`, `INSERT` | Nenhum acesso |

O banco `platform` foi extinto (decisão 0099) e não é acessado por nenhum processo.
