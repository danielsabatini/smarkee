# core.user: fluxo de dados (do `sk register` até `Ready`)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md). Segue **os dados** de um auto-cadastro de `core.user`, passo a passo: qual rota é chamada, qual é o payload de cada mensagem, o que cada componente grava no banco e com qual query. Os diagramas de [`01-caminho-perfeito`](flow/01-caminho-perfeito.mmd) e dos demais fluxos mostram *quem fala com quem*; aqui está *o que trafega e o que é gravado*.

**Origem dos exemplos.** Os exemplos foram montados a partir do código e dos schemas, **não** de uma execução. Os valores (UUIDs, e-mail, horários) são fictícios, e o `requestDigest` do exemplo foi calculado com o algoritmo do Receiver. Fontes de verdade: contratos em [`schemas/`](../../../../schemas), tabelas em [`manager/migrations/0001-user.sql`](../manager/migrations/0001-user.sql), semântica em [`docs/MESSAGING.md`](../../../../docs/MESSAGING.md), [`docs/NATS.md`](../../../../docs/NATS.md), [`docs/SSOT.md`](../../../../docs/SSOT.md) e [`docs/POSTGRESQL.md`](../../../../docs/POSTGRESQL.md). Este arquivo não as substitui: mostra um caso concreto.

**Comando.** `sk register` (`components/cli/src/sk/commands/register.py`) é o cliente deste fluxo. O passo 1 mostra o que ele envia e como trata a resposta.

## 0. Visão geral

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/users` (via gateway) | `{givenName, familyName, email}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `core."user"`, `core.user_operation`, `core.user_outbox` |
| 4 | Publisher → Manager (de volta) | NATS, Stream `DESIRED` | `desired` | `core.user_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `core."user"` (observação), `core.user_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → Zitadel; Executor → Manager | HTTP no Zitadel; NATS, Stream `RESULT` | `completed` | `core.user_action_result`, `core."user"` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `core."user"` → `Ready`, `core.user_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `core.user_outbox` |

Só o **Manager** escreve no SSOT de `core.user`. Receiver, Reconciler, Executor, Observer e Publisher não gravam nas tabelas de recurso (o Publisher só marca `published_at` no outbox).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver (no auto-cadastro) | UUIDv7 minúsculo (`^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$`) | Identidade do usuário. Vira o `userId` no Zitadel, e portanto o `sub` do token. |
| `operationId` | Receiver | UUIDv7 aleatório (sem `Idempotency-Key`); com a chave, SHA-256 determinístico | Identidade da Operation; a repetição do pedido produz o mesmo valor. |
| `requestDigest` | Receiver | SHA-256 hexadecimal (64 caracteres) do JSON canônico do pedido | Detecta o reuso do mesmo `operationId` com outro conteúdo. |
| `messageId` | Quem emite a mensagem | UUIDv7 | Identidade da mensagem; é o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | Receiver | UUIDv7 | Mesmo valor em toda a cadeia, para rastrear o pedido do início ao fim. |
| `causationId` | Quem emite | `messageId` da mensagem que causou esta | Encadeia causa e efeito. |
| `actionId` | Reconciler | `<resourceId>.<desiredGeneration>.<operation>.<messageId do observed>` | Identidade determinística da decisão; o Executor e o Manager a usam para ser idempotentes. |

### Valores usados nos exemplos

```text
resourceId      0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e
operationId     0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f
correlationId   0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02
requested       messageId 0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01
desired         messageId 0199c8b3-1a00-7c2d-8e3f-4a5b6c7d8e03
observed (1)    messageId 0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04   (absent)
action          messageId 0199c8b3-3a00-7c2d-8e3f-4a5b6c7d8e05
completed       messageId 0199c8b3-4a00-7c2d-8e3f-4a5b6c7d8e06
observed (2)    messageId 0199c8b3-5a00-7c2d-8e3f-4a5b6c7d8e07   (present)
```

## 1. CLI → Receiver: `POST /v1/users`

Comando:

```bash
sk register --name Ana --surname Souza --email ana.souza@example.com \
  [--api-url <url>] [--allow-insecure-http]
```

| Opção | Vira | Observação |
|---|---|---|
| `--name` | `givenName` | até 256 caracteres |
| `--surname` | `familyName` | até 256 caracteres |
| `--email` | `email` | também é o nome de login |
| `--api-url` | base da URL | parâmetro → `SK_CORE_API_URL` → `[core] apiUrl` do `config.toml`; sem valor, o comando falha com código 2 |
| `--allow-insecure-http` | | só em desenvolvimento; sem ele, URL sem HTTPS é recusada antes da chamada |

O comando valida os dados localmente, remove espaços das pontas (`strip`) e envia `POST <api-url>/v1/users` com `Content-Type: application/json`, **sem token** e sem `Idempotency-Key`. Em caso de sucesso mostra `resourceId` e `operationId` e orienta confirmar o e-mail, definir a senha e rodar `sk auth login`. Códigos de saída: `0` sucesso; `1` falha da API (`429`, `5xx`, rede); `2` uso (opção ausente, configuração, `400`).

Chamada HTTP:

| Item | Valor |
|---|---|
| Rota | `POST https://api-dev.smarkee.com.br/v1/users` (o gateway encaminha `/v1/users` ao `core-user-receiver`; veja `infrastructure/dev/gateway/bootstrap/routes.yml`) |
| Autenticação | **Nenhuma.** É a única escrita anônima; `requestedBy` vira `anonymous`. |
| Cabeçalho `Idempotency-Key` | Não se aplica ao cadastro (o Receiver passa `idempotency_key=None`). |
| Limite de taxa | Dois níveis: no gateway (por IP) e no Receiver (por origem). Estourou: `429` com `Retry-After`. |
| Contrato do corpo | [`schemas/core/user/api-create-request.v1.schema.json`](../../../../schemas/core/user/api-create-request.v1.schema.json) (`additionalProperties: false`) |

Corpo:

```json
{
  "givenName": "Ana",
  "familyName": "Souza",
  "email": "ana.souza@example.com"
}
```

| Campo | Tipo | Regra |
|---|---|---|
| `givenName` | string | 1 a 256 caracteres |
| `familyName` | string | 1 a 256 caracteres |
| `email` | string | formato e-mail, 3 a 254 caracteres; é também o nome de login |

Não há senha: a pessoa a define pela página do Zitadel, no link enviado por e-mail.

Resposta de sucesso, **uniforme**: o Receiver não consulta o SSOT, então o `202` é o mesmo exista ou não o e-mail (não revela cadastros):

```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f"
}
```

Erros: `400` (corpo inválido, com `field`), `429`, `503` (não conseguiu publicar no NATS, com `Retry-After: 5`). Formato dos erros: [`schemas/common/api-error.v1.schema.json`](../../../../schemas/common/api-error.v1.schema.json).

**Grava no banco:** nada.

## 2. Receiver → NATS: `requested`

O Receiver monta o envelope, calcula o `requestDigest` e publica no Stream `REQUESTED`.

**`requestDigest`:** SHA-256 de um JSON canônico (chaves ordenadas, sem espaços, UTF-8) deste conteúdo:

```json
{"operation":"create","specification":{"email":"ana.souza@example.com","familyName":"Souza","givenName":"Ana"}}
```

Resultado do exemplo: `d547829691a59178fe3795ce54bca04ccdfefff163dedb79f1f43fed9c67dae0`. Observe que o e-mail entra **como veio** no corpo; a normalização (minúsculas) é feita depois, pelo Manager.

| Item | Valor |
|---|---|
| Stream | `REQUESTED` (`WorkQueuePolicy`, `DiscardNew`) |
| Subject | `receiver.requested.core.user.<resourceId>.create` |
| Cabeçalho NATS | `Nats-Msg-Id: <messageId>` |
| Confirmação | O Receiver só responde `202` depois da confirmação do servidor (timeout de 5 s). Falhou: `503`. |

Payload (contrato: [`message-envelope.v1.schema.json`](../../../../schemas/common/message-envelope.v1.schema.json) e [`requested-create.v1.schema.json`](../../../../schemas/core/user/requested-create.v1.schema.json)):

```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01",
  "schemaVersion": "1.0",
  "messageType": "requested",
  "emitter": "receiver",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "create",
  "requestedBy": "anonymous",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "occurredAt": "2026-10-09T14:00:00+00:00",
  "publishedAt": "2026-10-09T14:00:00+00:00",
  "data": {
    "operationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f",
    "requestDigest": "d547829691a59178fe3795ce54bca04ccdfefff163dedb79f1f43fed9c67dae0",
    "specification": {
      "givenName": "Ana",
      "familyName": "Souza",
      "email": "ana.souza@example.com"
    }
  }
}
```

Campos do envelope (comuns a **todas** as mensagens deste documento): `messageId`, `schemaVersion`, `messageType`, `emitter`, `module`, `resourceType`, `resourceId`, `operation`, `occurredAt`, `publishedAt` e `data` são obrigatórios; os demais (`desiredGeneration`, `presence`, `observedAt`, `actionId`, `requestedBy`, `correlationId`, `causationId`, `publishedBy`) dependem do tipo da mensagem. O `data` tem no máximo 256 KiB. Mensagens são enviadas sem campos nulos.

**Grava no banco:** nada. A mensagem fica no Stream até o Manager confirmá-la (`ACK`).

## 3. Manager consome `requested` e grava no banco

Código: `manager/src/core_user_manager/handlers/requested.py` e `store/ssot.py`. O Manager consome o Stream `REQUESTED` pelo consumer durável `core-user-manager-requested`. Cada mensagem é **uma única transação**; o `ACK` só acontece **depois do `COMMIT`**.

### 3.1 Interpretação antes de gravar

1. Valida o envelope e confere `messageType = requested`, `emitter = receiver`, `module = core`, `resourceType = user`.
2. Exige `requestedBy` e `correlationId`.
3. Valida o `data` e **normaliza o e-mail**: `email.strip().lower()`.
4. Calcula o `desired` do cadastro (regra do User, `domain/user.py`). `platformRoles` vem da configuração do Manager (`CORE_USER_MANAGER_PLATFORM_ROLES`; [decisão 0025](../../../../.decisions/0025-roles-do-user-no-ssot.md)) e é a única fonte do conjunto de roles no loop:

```json
{
  "lifecycle": "present",
  "platformAccess": "granted",
  "platformRoles": [
    "organization.create",
    "organization.delete",
    "organization.get",
    "organization.list",
    "organization.update",
    "user.delete",
    "user.get"
  ],
  "givenName": "Ana",
  "familyName": "Souza",
  "email": "ana.souza@example.com"
}
```

A `reconciliation` **não** entra neste `desired`: é uma coluna à parte (mudá-la não incrementa a geração).

### 3.2 Queries, na ordem em que são executadas

Todas dentro da mesma transação, conectadas como o papel `core_user_manager`. Os nomes das tabelas vêm de `store/tables.py`.

**(a) Idempotência: esta Operation já foi aplicada?**

```sql
SELECT request_digest FROM core.user_operation WHERE operation_id = %s;
```

Se existir, nada é gravado e a mensagem é tratada como duplicada (resultado `DUPLICATE`). Se o digest gravado for diferente, o Manager registra um aviso de log.

**(b) Unicidade do e-mail: serializa a disputa e confere**

```sql
SELECT pg_advisory_xact_lock(hashtext('core.user.email:ana.souza@example.com'));

SELECT 1 FROM core."user"
 WHERE desired ->> 'email' = 'ana.souza@example.com'
   AND resource_id <> '0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e'
 LIMIT 1;
```

A trava consultiva dura até o fim da transação, então dois cadastros simultâneos do mesmo e-mail não passam juntos. Usa o índice `user_email` (`(desired ->> 'email')`). Se achar um registro, o caminho é o da seção 3.5 (rejeição).

**(c) Insere o recurso**

```sql
INSERT INTO core."user"
  (resource_id, schema_version, lifecycle, reconciliation,
   desired, desired_generation, resource_version, phase)
VALUES
  ('0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e', '1.0', 'present', 'active',
   '{"lifecycle":"present","platformAccess":"granted","platformRoles":["organization.create","organization.delete","organization.get","organization.list","organization.update","user.delete","user.get"],"givenName":"Ana","familyName":"Souza","email":"ana.souza@example.com"}'::jsonb,
   1, 1, 'Pending');
```

**(d) Insere a Operation**

```sql
INSERT INTO core.user_operation
  (operation_id, resource_id, operation_type, desired_generation, requested_by,
   correlation_id, request_digest, operation_status, operation_status_reason, completed_at)
VALUES
  ('0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f', '0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e', 'create',
   1, 'anonymous', '0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02',
   'd547829691a59178fe3795ce54bca04ccdfefff163dedb79f1f43fed9c67dae0',
   'accepted', NULL, NULL);
```

**(e) Insere a mensagem `desired` no outbox** (formato na seção 4)

```sql
INSERT INTO core.user_outbox (message_id, resource_id, subject, payload)
VALUES (%s, %s, %s, %s::jsonb);
```

Depois: `COMMIT` e só então `ACK` da mensagem `requested`.

### 3.3 Estado gravado ao final do passo 3

**`core."user"`** (uma linha):

| Coluna | Valor | Origem |
|---|---|---|
| `resource_id` | `0199c8a4-…3d4e` | `envelope.resourceId` |
| `schema_version` | `1.0` | constante do Manager |
| `lifecycle` | `present` | do `desired` |
| `reconciliation` | `active` | fixo na criação |
| `desired` | `{lifecycle, platformAccess, platformRoles, givenName, familyName, email}` (jsonb) | 3.1 |
| `desired_generation` | `1` | fixo na criação |
| `resource_version` | `1` | fixo na criação (aumenta a cada alteração da linha) |
| `observed` | `NULL` | ainda não observado |
| `presence` | `NULL` | idem |
| `observed_at` | `NULL` | idem (`presence` e `observed_at` são nulos juntos, por `CHECK`) |
| `phase` | `Pending` | fixo na criação |
| `conditions` | `[]` | default |
| `failure_count` | `0` | default |
| `created_at`, `updated_at` | `now()` | default |

**`core.user_operation`** (uma linha): `operation_status = accepted`, `desired_generation = 1`, `requested_by = anonymous`, `operation_status_reason = NULL`, `completed_at = NULL`, `created_at`/`updated_at = now()`.

**`core.user_outbox`** (uma linha): detalhada na seção 4.

### 3.4 Repetição e entrega duplicada

- Mesma mensagem reentregue pelo NATS (ou o cliente repetindo com o mesmo `operationId`): a query (a) encontra a Operation e **nada é gravado**.
- Duas entregas simultâneas disputando a chave primária: o `INSERT` falha com violação de unicidade, o Manager trata como duplicada (`DuplicateWriteError`).
- Falha transitória do banco: a exceção propaga, o `ACK` não é enviado e o NATS reentrega.

### 3.5 Cadastro rejeitado (e-mail já em uso)

Se a query (b) encontrar outro usuário com o mesmo e-mail, o Manager grava **só a Operation**, com:

```text
operation_status = 'rejected'   operation_status_reason = 'validation'   desired_generation = NULL
```

Não cria a linha em `core."user"` e **não** grava no outbox, portanto nada é publicado e nenhum e-mail é enviado. Para quem se cadastrou, a resposta foi o mesmo `202` do passo 1 (a Operation anônima só é legível por operadores). Veja [`03-email-ja-cadastrado`](flow/03-email-ja-cadastrado.mmd).

## 4. Outbox: o que fica gravado para ser publicado

Tabela `core.user_outbox` (DDL na migração). A linha é gravada na **mesma transação** do recurso, então "gravado e nunca publicado" não existe.

| Coluna | Valor | Observação |
|---|---|---|
| `sequence` | `1` | `bigint GENERATED ALWAYS AS IDENTITY`; define a ordem de publicação |
| `message_id` | `0199c8b3-1a00-7c2d-8e3f-4a5b6c7d8e03` | único; é o `messageId` do payload |
| `resource_id` | `0199c8a4-…3d4e` | |
| `subject` | `manager.desired.core.user.0199c8a4-…3d4e.changed` | |
| `payload` | JSON abaixo (jsonb, máx. 256 KiB) | |
| `created_at` | `now()` | |
| `published_at` | `NULL` | só o Publisher preenche |

`payload` (contrato do `data`: [`schemas/core/user/desired.v1.schema.json`](../../../../schemas/core/user/desired.v1.schema.json)):

```json
{
  "messageId": "0199c8b3-1a00-7c2d-8e3f-4a5b6c7d8e03",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "manager",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "requestedBy": "anonymous",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "causationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01",
  "occurredAt": "2026-10-09T14:00:01+00:00",
  "publishedAt": "2026-10-09T14:00:01+00:00",
  "data": {
    "lifecycle": "present",
    "reconciliation": "active",
    "platformAccess": "granted",
    "platformRoles": [
      "organization.create",
      "organization.delete",
      "organization.get",
      "organization.list",
      "organization.update",
      "user.delete",
      "user.get"
    ],
    "givenName": "Ana",
    "familyName": "Souza",
    "email": "ana.souza@example.com"
  }
}
```

Diferenças em relação ao `requested`: o `emitter` é `manager`, há `desiredGeneration`, o `causationId` aponta para o `messageId` do `requested`, e o `data` é o **estado desejado** (com `reconciliation`), não o pedido. O mesmo `correlationId` atravessa a cadeia.

## 5. Publisher: do outbox ao NATS

Código: `publisher/src/core_user_publisher/outbox/publication.py`. Conecta com o papel `core_user_publisher`, que só **lê** o outbox e **atualiza** `published_at`.

**Uma única instância publica por vez**, por trava consultiva de sessão:

```sql
SELECT pg_try_advisory_lock(hashtext('core.user_outbox'));
```

**Leitura de um lote** (em ordem, no máximo 100):

```sql
SELECT sequence, message_id, subject, payload
  FROM core.user_outbox
 WHERE published_at IS NULL
 ORDER BY sequence
 LIMIT 100;
```

**O que o Publisher acrescenta ao payload** antes de publicar:

| Campo | Valor |
|---|---|
| `publishedAt` | instante da publicação (substitui o gravado pelo Manager) |
| `publishedBy` | `core-user-publisher` (quem entregou; o `emitter` continua `manager`) |

**Publicação:** Stream `DESIRED` (`LimitsPolicy`, `MaxMsgsPerSubject=1`: guarda o último estado de cada recurso), subject do outbox, `Nats-Msg-Id = message_id`. Espera a confirmação do servidor, uma mensagem por vez; no primeiro erro interrompe o lote.

**Só depois da confirmação:**

```sql
UPDATE core.user_outbox SET published_at = now() WHERE sequence = ANY(%s);
```

Entrega **pelo menos uma vez**: se o processo cair entre a publicação e o `UPDATE`, a mensagem é republicada na volta, e o NATS descarta a duplicata pelo `Nats-Msg-Id` (janela de 120 s). Uma recusa permanente do transporte (por exemplo, `MaxPayloadError`) bloqueia a fila na ordem e tira o Publisher de `ready`.

Payload publicado em `DESIRED` = o do passo 4, mais `publishedBy` e o `publishedAt` atualizado.

## 6. A partir daqui: reconciliação até `Ready`

O `desired` publicado dispara o loop (veja [`01-caminho-perfeito`](flow/01-caminho-perfeito.mmd)). O Observer, o Reconciler e o Executor **não gravam no SSOT**; o que chega ao banco passa sempre pelo Manager.

### 6.1 Observer publica `observed` com `absent`

O Observer lê o Zitadel (conta somente leitura). Como o usuário ainda não existe, o resultado é `absent` (404 inequívoco).

| Item | Valor |
|---|---|
| Stream | `OBSERVED` (`LimitsPolicy`, `MaxMsgsPerSubject=1`, `MaxAge`) |
| Subject | `observer.observed.core.user.<resourceId>.changed` |
| Contrato do `data` | [`schemas/core/user/observed.v1.schema.json`](../../../../schemas/core/user/observed.v1.schema.json) |

```json
{
  "messageId": "0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04",
  "schemaVersion": "1.0",
  "messageType": "observed",
  "emitter": "observer",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "presence": "absent",
  "observedAt": "2026-10-09T14:00:02+00:00",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "occurredAt": "2026-10-09T14:00:02+00:00",
  "publishedAt": "2026-10-09T14:00:02+00:00",
  "data": {}
}
```

Valores de `presence`: `present`, `absent` ou `unknown` (qualquer falha do Zitadel que não seja o 404 inequívoco é `unknown`, nunca `absent`).

**Manager aplica o `observed`** (`handlers/observed.py`; uma transação): trava a linha, ignora a observação se `observed_at` gravado for igual ou mais recente, recalcula `phase` e `conditions` e grava.

```sql
SELECT resource_version, desired_generation, lifecycle, reconciliation, desired, phase,
       conditions, failure_count, observed_at
  FROM core."user" WHERE resource_id = %s FOR UPDATE;

UPDATE core."user"
   SET observed = %s, presence = %s, observed_at = %s, conditions = %s, phase = %s,
       resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = %s
RETURNING resource_version;
```

Em seguida acerta as Operations da geração atual (`settle_operations`): as de geração **anterior** ainda abertas viram `failed`; as da atual viram `completed` se convergiu, senão `in_progress`:

```sql
UPDATE core.user_operation SET operation_status = 'failed', updated_at = now(), completed_at = now()
 WHERE resource_id = %s AND operation_status IN ('accepted','in_progress') AND desired_generation < %s;

UPDATE core.user_operation SET operation_status = %s, updated_at = now(),
       completed_at = CASE WHEN %s THEN now() ELSE completed_at END
 WHERE resource_id = %s AND operation_status IN ('accepted','in_progress') AND desired_generation = %s;
```

E grava no outbox uma mensagem `updated` (formato na seção 6.5).

Resultado para o `absent` (não convergiu): `observed = {}`, `presence = absent`, `observed_at` preenchido, `phase = Reconciling`, `conditions` com `Ready = False` (`reason: Reconciling`), `resource_version = 2`; Operation passa a `in_progress`.

### 6.2 Reconciler decide e publica `action`

O Reconciler mantém em memória o último `desired` e o último `observed` de cada usuário (nenhum acesso ao banco). Com `desired.lifecycle = present` e `observed.presence = absent`, decide **`create`**, motivo `Missing`.

| Item | Valor |
|---|---|
| Stream | `ACTION` (`WorkQueuePolicy`, `DiscardNew`; particionado por `resourceId` no servidor, transparente para quem publica) |
| Subject | `reconciler.action.core.user.<resourceId>.create` |
| Cabeçalho NATS | `Nats-Msg-Id: <actionId>` |
| `actionId` | `<resourceId>.<desiredGeneration>.<operation>.<messageId do observed>` |

```json
{
  "messageId": "0199c8b3-3a00-7c2d-8e3f-4a5b6c7d8e05",
  "schemaVersion": "1.0",
  "messageType": "action",
  "emitter": "reconciler",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "create",
  "actionId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e.1.create.0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04",
  "desiredGeneration": 1,
  "requestedBy": "anonymous",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "causationId": "0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04",
  "occurredAt": "2026-10-09T14:00:03+00:00",
  "publishedAt": "2026-10-09T14:00:03+00:00",
  "data": {
    "reason": "Missing",
    "message": "The user does not exist in the identity provider."
  }
}
```

A `action` **não carrega os dados do usuário**: o Executor lê o `desired` vigente (último valor do Stream `DESIRED`, por leitura direta) e revalida geração e reconciliação ativa antes de agir. **Grava no banco:** nada.

### 6.3 Executor age no Zitadel e publica `completed` (ou `failed`)

No `create`, o Executor chama o Zitadel (nesta ordem, cada passo idempotente): cria o usuário humano **sem senha**, com `userId = resourceId`; dispara o e-mail "Verificar e-mail"; dispara o "Redefinir senha"; concede no projeto `smarkee` as roles de `desired.platformRoles` (o Executor não tem lista própria; sem o campo no `desired`, a ação é rejeitada sem retentativa). Antes disso consulta o `RESULT` para saber se aquele `actionId` já tem desfecho (idempotência).

| Item | Valor |
|---|---|
| Stream | `RESULT` (`LimitsPolicy`, `MaxAge`, `allow_direct`) |
| Subject | `executor.completed.core.user.<resourceId>.create` (ou `executor.failed...`) |

```json
{
  "messageId": "0199c8b3-4a00-7c2d-8e3f-4a5b6c7d8e06",
  "schemaVersion": "1.0",
  "messageType": "completed",
  "emitter": "executor",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "create",
  "actionId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e.1.create.0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04",
  "desiredGeneration": 1,
  "requestedBy": "anonymous",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "causationId": "0199c8b3-3a00-7c2d-8e3f-4a5b6c7d8e05",
  "occurredAt": "2026-10-09T14:00:04+00:00",
  "publishedAt": "2026-10-09T14:00:04+00:00",
  "data": {}
}
```

Em falha, `messageType` é `failed` e o `data` é `{"reason": "...", "retryable": true|false, "message": "..."}` (por exemplo `{"reason":"ProviderUnavailable","retryable":true}`). O Executor **não decide retry**: o Reconciler reemite com *backoff*.

**Manager aplica o resultado** (`handlers/result.py`; uma transação):

```sql
SELECT ... FROM core."user" WHERE resource_id = %s FOR UPDATE;

INSERT INTO core.user_action_result (action_id, resource_id, desired_generation, action_outcome)
VALUES (%s, %s, %s, 'completed')
ON CONFLICT (action_id) DO NOTHING
RETURNING action_id;
```

Se o `INSERT` não devolver linha, o `actionId` já foi contabilizado e nada mais é feito (`DUPLICATE`). Se a `desiredGeneration` da mensagem não for a vigente, é ignorada (a especificação foi substituída). Senão:

```sql
UPDATE core."user"
   SET failure_count = %s, phase = %s, reconciliation = %s, conditions = %s,
       resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = %s RETURNING resource_version;

UPDATE core.user_operation SET operation_status = 'in_progress', updated_at = now(),
       completed_at = CASE WHEN false THEN now() ELSE completed_at END
 WHERE resource_id = %s AND operation_status IN ('accepted','in_progress') AND desired_generation = %s;
```

Mais um `updated` no outbox. Para o `completed`: `failure_count` continua `0`, `phase = Reconciling` (se estava `Pending`), `resource_version = 3`. Para `failed`: `failure_count + 1`; ao chegar a **5 falhas na mesma geração**, `phase = Failed`, `reconciliation = suspended`, a Operation vira `failed` e o Manager republica o `desired` com `reconciliation: suspended` pelo outbox.

**`core.user_action_result`** (uma linha por resultado):

| Coluna | Valor |
|---|---|
| `action_id` | `0199c8a4-…3d4e.1.create.0199c8b3-2a00-…8e04` |
| `resource_id` | `0199c8a4-…3d4e` |
| `desired_generation` | `1` |
| `action_outcome` | `completed` (ou `failed`) |
| `recorded_at` | `now()` |

### 6.4 Observer observa de novo: `present` e `Ready`

Depois do `completed` o Observer observa o usuário de novo (`causationId` = `messageId` do `completed`). Agora o usuário existe:

```json
{
  "messageId": "0199c8b3-5a00-7c2d-8e3f-4a5b6c7d8e07",
  "schemaVersion": "1.0",
  "messageType": "observed",
  "emitter": "observer",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "presence": "present",
  "observedAt": "2026-10-09T14:00:05+00:00",
  "causationId": "0199c8b3-4a00-7c2d-8e3f-4a5b6c7d8e06",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "occurredAt": "2026-10-09T14:00:05+00:00",
  "publishedAt": "2026-10-09T14:00:05+00:00",
  "data": {
    "emailVerified": false,
    "userState": "initial",
    "platformAccess": "granted",
    "platformRoles": [
      "organization.create",
      "organization.delete",
      "organization.get",
      "organization.list",
      "organization.update",
      "user.delete",
      "user.get"
    ]
  }
}
```

| Campo de `data` | Valores |
|---|---|
| `emailVerified` | `true` / `false` |
| `userState` | `initial` enquanto a senha não foi definida; depois `active` ou `inactive` |
| `platformAccess` | `granted` se o usuário tem ao menos uma role no projeto; senão `revoked` |
| `platformRoles` | Roles que o usuário tem no projeto `smarkee`, em ordem alfabética (inclui roles a mais, como `platform.admin` de um operador) |

O Manager aplica pela mesma sequência da seção 6.1. **Convergência** do User: `presence = present`, `observed.platformAccess == desired.platformAccess` **e** `desired.platformRoles ⊆ observed.platformRoles` (roles a mais não divergem; role faltando gera `update` com `reason = Drift`); `emailVerified` e `userState` **não** entram na comparação. Convergiu, então:

| Onde | Valor final |
|---|---|
| `core."user".observed` | `{"emailVerified": false, "userState": "initial", "platformAccess": "granted", "platformRoles": [...as 7 roles...]}` |
| `core."user".presence` / `observed_at` | `present` / `2026-10-09T14:00:05+00:00` |
| `core."user".phase` | `Ready` |
| `core."user".conditions` | `[{"type":"Ready","status":"True","reason":"Reconciled","observedGeneration":1,"lastTransitionAt":"2026-10-09T14:00:05+00:00"}]` |
| `core."user".resource_version` | `4` |
| `core.user_operation.operation_status` | `completed` (`completed_at` preenchido) |

Do ponto de vista dos dados, o cadastro termina aqui. A pessoa ainda precisa clicar nos links e definir a senha; isso não é gravado pelo SSOT até uma nova observação (`userState` passa de `initial` a `active`, `emailVerified` a `true`, e `resource_version` sobe).

### 6.5 `updated`: o fato "mudou de fase"

A cada gravação do Manager que muda o estado observável (cada `observed` e cada resultado), ele grava no outbox uma mensagem `updated`, publicada depois pelo Publisher no Stream `UPDATED` (`LimitsPolicy`, `MaxAge`; consumida por console, auditoria e métricas).

Subject: `manager.updated.core.user.<resourceId>.changed`. Contrato do `data`: [`updated.v1.schema.json`](../../../../schemas/common/updated.v1.schema.json).

```json
{
  "messageId": "0199c8b3-6a00-7c2d-8e3f-4a5b6c7d8e08",
  "schemaVersion": "1.0",
  "messageType": "updated",
  "emitter": "manager",
  "module": "core",
  "resourceType": "user",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "causationId": "0199c8b3-5a00-7c2d-8e3f-4a5b6c7d8e07",
  "occurredAt": "2026-10-09T14:00:05+00:00",
  "publishedAt": "2026-10-09T14:00:05+00:00",
  "data": {
    "phase": "Ready",
    "lifecycle": "present",
    "resourceVersion": "4"
  }
}
```

Na remoção convergida, o `data` ganha `"removed": true`.

### 6.6 Linha do tempo do banco (cadastro bem-sucedido)

| Momento | `phase` | `resource_version` | `presence` | `failure_count` | `user_operation.operation_status` | Linhas novas no outbox |
|---|---|---|---|---|---|---|
| Passo 3 (`requested`) | `Pending` | 1 | `NULL` | 0 | `accepted` | `desired` |
| `observed` (`absent`) | `Reconciling` | 2 | `absent` | 0 | `in_progress` | `updated` |
| `completed` | `Reconciling` | 3 | `absent` | 0 | `in_progress` | `updated` |
| `observed` (`present`) | `Ready` | 4 | `present` | 0 | `completed` | `updated` |

A ordem entre `observed` e `completed` pode variar (são mensagens de Streams distintos); a tabela mostra a sequência típica. O resultado final não depende da ordem: `observed_at` nunca retrocede e `actionId` é contabilizado uma vez.

## 7. Leitura: `GET`

A API **nunca lê as tabelas**: só as views versionadas (decisão 0004), com o papel `core_user_receiver`, que tem `SELECT` apenas nelas.

| Rota | View | Quem lê |
|---|---|---|
| `GET /v1/users/{id}` | `core.user_v1` | O próprio usuário ou `platform.admin`; outro usuário recebe `404` |
| `GET /v1/users/{id}/operations/{operationId}` | `core.user_operation_v1` | O solicitante ou `platform.admin`; a Operation de cadastro anônimo só é legível por operadores |

`core.user_v1` expõe `resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation, resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at`, **sem `failure_count`**. `core.user_operation_v1` expõe as colunas de `core.user_operation` sem `correlation_id`; `requested_by` está nela só para o Receiver autorizar a leitura. O formato JSON devolvido está em [`schemas/core/user/resource.example.json`](../../../../schemas/core/user/resource.example.json) e [`schemas/common/operation.example.json`](../../../../schemas/common/operation.example.json).

Para conferir o banco no ambiente de dev (somente leitura, como o dono):

```sql
SELECT resource_id, phase, resource_version, presence, failure_count FROM core."user";
SELECT operation_id, operation_type, operation_status, operation_status_reason, desired_generation
  FROM core.user_operation ORDER BY created_at DESC;
SELECT sequence, subject, published_at FROM core.user_outbox ORDER BY sequence;
```

## 8. Remoção: `DELETE /v1/users/{id}?resourceVersion=`

Resumo dos dados (fluxo completo: [`08-remocao`](flow/08-remocao.mmd)). Exige token com a role `user.delete`; o dono ou `platform.admin`. `resourceVersion` é obrigatório e deve ser o da última leitura (senão `409`). Aceita `Idempotency-Key` (o mesmo valor com outro conteúdo devolve `422`).

- **`requestDigest`:** SHA-256 de `{"operation":"delete","resourceId":"<id>","resourceVersion":"<versão>"}`.
- **`requested`:** subject `receiver.requested.core.user.<resourceId>.delete`; `requestedBy` = `sub` do token; `data = {operationId, requestDigest, resourceVersion}` (contrato: [`requested-delete.v1.schema.json`](../../../../schemas/core/user/requested-delete.v1.schema.json)).
- **Manager** (transação): `SELECT ... FOR UPDATE` na linha; se não existir, Operation `rejected/not_found`; se `resource_version` diferir, `rejected/conflict`. Calcula o novo `desired` **sem dados pessoais**: `{"lifecycle":"absent","platformAccess":"granted","platformRoles":[...]}` (as roles atuais são copiadas; nenhum dado pessoal). Grava:

```sql
UPDATE core."user"
   SET lifecycle = 'absent', reconciliation = %s, desired = %s,
       desired_generation = desired_generation + 1, failure_count = 0,
       phase = 'Deleting', resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = %s AND resource_version = %s
RETURNING desired_generation;
```

  Mais `INSERT` na `core.user_operation` (`delete`, `accepted`, geração 2) e o `desired` no outbox.
- **Loop:** o Reconciler decide `delete` (motivo `DeletionRequested`); o Executor remove o usuário no Zitadel (ausente também é sucesso) e publica `completed`; o Observer observa `absent`.
- **Convergência:** o Manager marca a Operation como `completed`, executa `DELETE FROM core."user" WHERE resource_id = %s` e grava um `updated` com `"removed": true`. As linhas de `core.user_operation`, `core.user_action_result` e `core.user_outbox` **permanecem** até a limpeza por retenção (papel `core_maintenance`, que só tem `SELECT`/`DELETE` nelas).

## 9. Mapa: quem grava o quê

| Mensagem recebida pelo Manager | `core."user"` | `core.user_operation` | `core.user_action_result` | `core.user_outbox` |
|---|---|---|---|---|
| `requested` / `create` | `INSERT` (`Pending`, geração 1) | `INSERT` (`accepted`, ou `rejected`) | | `INSERT` `desired` |
| `requested` / `delete` | `UPDATE` (`absent`, geração +1, `Deleting`) | `INSERT` (`accepted`, ou `rejected`) | | `INSERT` `desired` |
| `observed` | `UPDATE` (observação, `conditions`, `phase`); `DELETE` se a remoção convergiu | `UPDATE` (`in_progress`, `completed`, ou `failed` nas gerações antigas) | | `INSERT` `updated` |
| `completed` / `failed` | `UPDATE` (`failure_count`, `phase`, `conditions`, `reconciliation`) | `UPDATE` (`in_progress`, ou `failed` ao suspender) | `INSERT` (uma vez por `actionId`) | `INSERT` `updated` (e `desired` suspenso no limite de falhas) |

| Papel de banco | Privilégio |
|---|---|
| `core_user_manager` | `SELECT`/`INSERT`/`UPDATE`/`DELETE` em `core."user"`; `SELECT`/`INSERT`/`UPDATE` em `user_operation`; `SELECT`/`INSERT` em `user_action_result`; só `INSERT` em `user_outbox` |
| `core_user_receiver` | `SELECT` em `user_v1` e `user_operation_v1` |
| `core_user_publisher` | `SELECT` em `user_outbox` e `UPDATE (published_at)` |
| `core_maintenance` | `SELECT`/`DELETE` em `user_outbox`, `user_action_result` e `user_operation` |

Origem: bloco `GRANT` de [`manager/migrations/0001-user.sql`](../manager/migrations/0001-user.sql). O schema físico completo está em [`database/01-er-fisico.mmd`](database/01-er-fisico.mmd).

> **Atenção ao ler o diagrama físico.** O ER físico usa nomes como `core_user_operation` e `core_user_outbox`, e descreve `operation_type` como "create ou delete (sem update)". A migração cria `core.user_operation` e `core.user_outbox` (schema `core`, tabela `user_...`) e o seu `CHECK` aceita também `'update'`. Em caso de divergência, vale a migração.
