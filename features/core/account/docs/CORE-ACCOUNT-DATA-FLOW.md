# core.account: fluxo de dados (do `sk register` até `Ready`)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md). Segue **os dados** de um auto-cadastro de `core.account`, passo a passo: qual rota é chamada, qual é o payload de cada mensagem, o que cada componente grava no banco e com qual query. Os diagramas de [`01-caminho-perfeito`](flow/01-caminho-perfeito.mmd) e dos demais fluxos mostram *quem fala com quem*; aqui está *o que trafega e o que é gravado*.

**Origem dos exemplos.** Os exemplos foram montados a partir do código e dos schemas, **não** de uma execução. Os valores (UUIDs, e-mail, horários) são fictícios, e o `requestDigest` do exemplo foi calculado com o algoritmo do Receiver. Fontes de verdade: contratos em [`schemas/`](../../../../schemas), tabelas em [`migrations/0001-account.sql`](../migrations/0001-account.sql), semântica em [`docs/messaging/MESSAGING.md`](../../../../docs/messaging/MESSAGING.md), [`docs/messaging/NATS.md`](../../../../docs/messaging/NATS.md), [`docs/data/SSOT.md`](../../../../docs/data/SSOT.md) e [`docs/data/POSTGRESQL.md`](../../../../docs/data/POSTGRESQL.md). Este arquivo não as substitui: mostra um caso concreto.

**Comando.** `sk register` (`clients/cli/src/sk/commands/register.py`) é o cliente deste fluxo. O passo 1 mostra o que ele envia e como trata a resposta.

## 0. Visão geral

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/core/accounts` (via gateway) | `{givenName, familyName, email}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `core.account`, `core.account_operation`, `core.account_outbox` |
| 4 | Publisher → Manager (de volta) | NATS, Stream `DESIRED` | `desired` | `core.account_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `core.account` (observação), `core.account_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → Zitadel; Executor → Manager | HTTP no Zitadel; NATS, Stream `RESULT` | `completed` | `core.account_action_result`, `core.account` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `core.account` → `Ready`, `core.account_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `core.account_outbox` |

Só o **Manager** escreve no SSOT de `core.account`. Receiver, Reconciler, Executor, Observer e Publisher não gravam nas tabelas de recurso (o Publisher só marca `published_at` no outbox).

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

## 1. CLI → Receiver: `POST /v1/core/accounts`

Comando:

```bash
sk register --name Ana --surname Souza --email ana.souza@example.com
```

| Opção | Vira | Observação |
|---|---|---|
| `--name` | `givenName` | até 256 caracteres |
| `--surname` | `familyName` | até 256 caracteres |
| `--email` | `email` | também é o nome de login |

O comando valida os dados localmente, remove espaços das pontas (`strip`) e envia `POST <api-url>/v1/core/accounts` com `Content-Type: application/json`, **sem token** e sem `Idempotency-Key`. Em caso de sucesso mostra `resourceId` e `operationId` e orienta confirmar o e-mail, definir a senha e rodar `sk auth login`. Códigos de saída: `0` sucesso; `1` falha da API (`429`, `5xx`, rede); `2` uso (opção ausente, configuração, `400`).

Chamada HTTP:

| Item | Valor |
|---|---|
| Rota | `POST https://api-dev.smarkee.com.br/v1/core/accounts` (o gateway encaminha `/v1/core/accounts` ao `core-account-receiver`; veja `infrastructure/dev/gateway/bootstrap/adc.yaml`) |
| Autenticação | **Nenhuma.** É a única escrita anônima; `requestedBy` vira `anonymous`. |
| Cabeçalho `Idempotency-Key` | Não se aplica ao cadastro (o Receiver passa `idempotency_key=None`). |
| Limite de taxa | Dois níveis: no gateway (por IP) e no Receiver (por origem). Estourou: `429` com `Retry-After`. |
| Contrato do corpo | [`schemas/core/account/api-create-request.v1.schema.json`](../../../../schemas/core/account/api-create-request.v1.schema.json) (`additionalProperties: false`) |

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
| Subject | `receiver.requested.core.account.<resourceId>.create` |
| Cabeçalho NATS | `Nats-Msg-Id: <messageId>` |
| Confirmação | O Receiver só responde `202` depois da confirmação do servidor (timeout de 5 s). Falhou: `503`. |

Payload (contrato: [`message-envelope.v1.schema.json`](../../../../schemas/common/message-envelope.v1.schema.json) e [`requested-create.v1.schema.json`](../../../../schemas/core/account/requested-create.v1.schema.json)):

```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01",
  "schemaVersion": "1.0",
  "messageType": "requested",
  "emitter": "receiver",
  "module": "core",
  "resourceType": "account",
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

Código: `src/core_account/manager/handlers/requested.py` e `store/ssot.py`. O Manager consome o Stream `REQUESTED` pelo consumer durável `core-account-manager-requested`. Cada mensagem é **uma única transação**; o `ACK` só acontece **depois do `COMMIT`**.

### 3.1 Interpretação antes de gravar

1. Valida o envelope e confere `messageType = requested`, `emitter = receiver`, `module = core`, `resourceType = account`.
2. Exige `requestedBy` e `correlationId`.
3. Valida o `data` e **normaliza o e-mail**: `email.strip().lower()`.
4. Calcula o `desired` do cadastro (regra da Account, `domain/account.py`). `platformPermissions` vem da configuração do Manager (`CORE_ACCOUNT_MANAGER_PLATFORM_PERMISSIONS`; [decisão 0025](../../../../.decisions/0025-roles-do-account-no-ssot.md)) e é a única fonte do conjunto de permissões no loop:

```json
{
  "lifecycle": "present",
  "platformAccess": "granted",
  "platformPermissions": [
    "core.account.delete",
    "core.account.get",
    "sum.ipm.disable",
    "sum.ipm.enable",
    "sum.ipm.get"
  ],
  "givenName": "Ana",
  "familyName": "Souza",
  "email": "ana.souza@example.com"
}
```

A `reconciliation` **não** entra neste `desired`: é uma coluna à parte (mudá-la não incrementa a geração).

### 3.2 Queries, na ordem em que são executadas

Todas dentro da mesma transação, conectadas como o papel `core_account_manager`. Os nomes das tabelas vêm de `store/tables.py`.

**(a) Idempotência: esta Operation já foi aplicada?**

```sql
SELECT request_digest FROM core.account_operation WHERE operation_id = %s;
```

Se existir, nada é gravado e a mensagem é tratada como duplicada (resultado `DUPLICATE`). Se o digest gravado for diferente, o Manager registra um aviso de log.

**(b) Unicidade do e-mail: serializa a disputa e confere**

```sql
SELECT pg_advisory_xact_lock(hashtext('core.account.email:ana.souza@example.com'));

SELECT 1 FROM core.account
 WHERE desired ->> 'email' = 'ana.souza@example.com'
   AND resource_id <> '0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e'
 LIMIT 1;
```

A trava consultiva dura até o fim da transação, então dois cadastros simultâneos do mesmo e-mail não passam juntos. Usa o índice `account_email` (`(desired ->> 'email')`). Se achar um registro, o caminho é o da seção 3.5 (rejeição).

**(c) Insere o recurso**

```sql
INSERT INTO core.account
  (resource_id, schema_version, lifecycle, reconciliation,
   desired, desired_generation, resource_version, phase)
VALUES
  ('0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e', '1.0', 'present', 'active',
   '{"lifecycle":"present","platformAccess":"granted","platformPermissions":["core.account.delete","core.account.get","sum.ipm.disable","sum.ipm.enable","sum.ipm.get"],"givenName":"Ana","familyName":"Souza","email":"ana.souza@example.com"}'::jsonb,
   1, 1, 'Pending');
```

**(d) Insere a Operation**

```sql
INSERT INTO core.account_operation
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
INSERT INTO core.account_outbox (message_id, resource_id, subject, payload)
VALUES (%s, %s, %s, %s::jsonb);
```

Depois: `COMMIT` e só então `ACK` da mensagem `requested`.

### 3.3 Estado gravado ao final do passo 3

**`core.account`** (uma linha):

| Coluna | Valor | Origem |
|---|---|---|
| `resource_id` | `0199c8a4-…3d4e` | `envelope.resourceId` |
| `schema_version` | `1.0` | constante do Manager |
| `lifecycle` | `present` | do `desired` |
| `reconciliation` | `active` | fixo na criação |
| `desired` | `{lifecycle, platformAccess, platformPermissions, givenName, familyName, email}` (jsonb) | 3.1 |
| `desired_generation` | `1` | fixo na criação |
| `resource_version` | `1` | fixo na criação (aumenta a cada alteração da linha) |
| `observed` | `NULL` | ainda não observado |
| `presence` | `NULL` | idem |
| `observed_at` | `NULL` | idem (`presence` e `observed_at` são nulos juntos, por `CHECK`) |
| `phase` | `Pending` | fixo na criação |
| `conditions` | `[]` | default |
| `failure_count` | `0` | default |
| `created_at`, `updated_at` | `now()` | default |

**`core.account_operation`** (uma linha): `operation_status = accepted`, `desired_generation = 1`, `requested_by = anonymous`, `operation_status_reason = NULL`, `completed_at = NULL`, `created_at`/`updated_at = now()`.

**`core.account_outbox`** (uma linha): detalhada na seção 4.

### 3.4 Repetição e entrega duplicada

- Mesma mensagem reentregue pelo NATS (ou o cliente repetindo com o mesmo `operationId`): a query (a) encontra a Operation e **nada é gravado**.
- Duas entregas simultâneas disputando a chave primária: o `INSERT` falha com violação de unicidade, o Manager trata como duplicada (`DuplicateWriteError`).
- Falha transitória do banco: a exceção propaga, o `ACK` não é enviado e o NATS reentrega.

### 3.5 Cadastro rejeitado (e-mail já em uso)

Se a query (b) encontrar outro usuário com o mesmo e-mail, o Manager grava **só a Operation**, com:

```text
operation_status = 'rejected'   operation_status_reason = 'validation'   desired_generation = NULL
```

Não cria a linha em `core.account` e **não** grava no outbox, portanto nada é publicado e nenhum e-mail é enviado. Para quem se cadastrou, a resposta foi o mesmo `202` do passo 1 (a Operation anônima só é legível por operadores). Veja [`03-email-ja-cadastrado`](flow/03-email-ja-cadastrado.mmd).

## 4. Outbox: o que fica gravado para ser publicado

Tabela `core.account_outbox` (DDL na migração). A linha é gravada na **mesma transação** do recurso, então "gravado e nunca publicado" não existe.

| Coluna | Valor | Observação |
|---|---|---|
| `sequence` | `1` | `bigint GENERATED ALWAYS AS IDENTITY`; define a ordem de publicação |
| `message_id` | `0199c8b3-1a00-7c2d-8e3f-4a5b6c7d8e03` | único; é o `messageId` do payload |
| `resource_id` | `0199c8a4-…3d4e` | |
| `subject` | `manager.desired.core.account.0199c8a4-…3d4e.changed` | |
| `payload` | JSON abaixo (jsonb, máx. 256 KiB) | |
| `created_at` | `now()` | |
| `published_at` | `NULL` | só o Publisher preenche |

`payload` (contrato do `data`: [`schemas/core/account/desired.v1.schema.json`](../../../../schemas/core/account/desired.v1.schema.json)):

```json
{
  "messageId": "0199c8b3-1a00-7c2d-8e3f-4a5b6c7d8e03",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "manager",
  "module": "core",
  "resourceType": "account",
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
    "platformPermissions": [
      "core.account.delete",
      "core.account.get",
      "sum.ipm.disable",
      "sum.ipm.enable",
      "sum.ipm.get"
    ],
    "givenName": "Ana",
    "familyName": "Souza",
    "email": "ana.souza@example.com"
  }
}
```

Diferenças em relação ao `requested`: o `emitter` é `manager`, há `desiredGeneration`, o `causationId` aponta para o `messageId` do `requested`, e o `data` é o **estado desejado** (com `reconciliation`), não o pedido. O mesmo `correlationId` atravessa a cadeia.

## 5. Publisher: do outbox ao NATS

Código: `src/core_account/publisher/outbox/publication.py`. Conecta com o papel `core_account_publisher`, que só **lê** o outbox e **atualiza** `published_at`.

**Uma única instância publica por vez**, por trava consultiva de sessão:

```sql
SELECT pg_try_advisory_lock(hashtext('core.account_outbox'));
```

**Leitura de um lote** (em ordem, no máximo 100):

```sql
SELECT sequence, message_id, subject, payload
  FROM core.account_outbox
 WHERE published_at IS NULL
 ORDER BY sequence
 LIMIT 100;
```

**O que o Publisher acrescenta ao payload** antes de publicar:

| Campo | Valor |
|---|---|
| `publishedAt` | instante da publicação (substitui o gravado pelo Manager) |
| `publishedBy` | `core-account-publisher` (quem entregou; o `emitter` continua `manager`) |

**Publicação:** Stream `DESIRED` (`LimitsPolicy`, `MaxMsgsPerSubject=1`: guarda o último estado de cada recurso), subject do outbox, `Nats-Msg-Id = message_id`. Espera a confirmação do servidor, uma mensagem por vez; no primeiro erro interrompe o lote.

**Só depois da confirmação:**

```sql
UPDATE core.account_outbox SET published_at = now() WHERE sequence = ANY(%s);
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
| Subject | `observer.observed.core.account.<resourceId>.changed` |
| Contrato do `data` | [`schemas/core/account/observed.v1.schema.json`](../../../../schemas/core/account/observed.v1.schema.json) |

```json
{
  "messageId": "0199c8b3-2a00-7c2d-8e3f-4a5b6c7d8e04",
  "schemaVersion": "1.0",
  "messageType": "observed",
  "emitter": "observer",
  "module": "core",
  "resourceType": "account",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "presence": "absent",
  "observedAt": "2026-10-09T14:00:02+00:00",
  "observedGeneration": 1,
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "occurredAt": "2026-10-09T14:00:02+00:00",
  "publishedAt": "2026-10-09T14:00:02+00:00",
  "data": {}
}
```

Valores de `presence`: `present`, `absent` ou `unknown` (qualquer falha do Zitadel que não seja o 404 inequívoco é `unknown`, nunca `absent`). `observedGeneration` é a geração que o Observer conhecia **antes** de ler o Zitadel (decisão 0072): só uma observação feita depois de uma geração pode confirmá-la.

**Manager aplica o `observed`** (`handlers/observed.py`; uma transação): trava a linha, ignora a observação se `observed_at` gravado for igual ou mais recente, recalcula `phase` e `conditions` e grava. A geração atual só é **confirmada** quando o conteúdo converge **e** o `observedGeneration` da mensagem é igual a `desired_generation` (decisão 0072); então `observed_generation` recebe a geração.

```sql
SELECT resource_version, desired_generation, lifecycle, reconciliation, desired, phase,
       conditions, failure_count, observed_at, observed_generation
  FROM core.account WHERE resource_id = %s FOR UPDATE;

UPDATE core.account
   SET observed = %s, presence = %s, observed_at = %s, conditions = %s, phase = %s,
       observed_generation = GREATEST(observed_generation, %s),  -- a geração confirmada, ou nulo
       resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = %s
RETURNING resource_version;
```

Em seguida acerta as Operations da geração atual (`settle_operations`): as de geração **anterior** ainda abertas viram `failed`; as da atual viram `completed` se a geração foi confirmada, senão `in_progress`:

```sql
UPDATE core.account_operation SET operation_status = 'failed', updated_at = now(), completed_at = now()
 WHERE resource_id = %s AND operation_status IN ('accepted','in_progress') AND desired_generation < %s;

UPDATE core.account_operation SET operation_status = %s, updated_at = now(),
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
| Subject | `reconciler.action.core.account.<resourceId>.create` |
| Cabeçalho NATS | `Nats-Msg-Id: <actionId>` |
| `actionId` | `<resourceId>.<desiredGeneration>.<operation>.<messageId do observed>` |

```json
{
  "messageId": "0199c8b3-3a00-7c2d-8e3f-4a5b6c7d8e05",
  "schemaVersion": "1.0",
  "messageType": "action",
  "emitter": "reconciler",
  "module": "core",
  "resourceType": "account",
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
    "message": "The account does not exist in the identity provider."
  }
}
```

A `action` **não carrega os dados do usuário**: o Executor lê o `desired` vigente (último valor do Stream `DESIRED`, por leitura direta) e revalida geração e reconciliação ativa antes de agir. **Grava no banco:** nada.

### 6.3 Executor age no Zitadel e publica `completed` (ou `failed`)

No `create`, o Executor chama o Zitadel (nesta ordem, cada passo idempotente): cria o usuário humano **sem senha**, com `userId = resourceId`; o Zitadel dispara, na criação, o e-mail "Verificar e-mail", cuja página também define a senha (um e-mail só; o "Redefinir senha" fica para quem esquecer a senha); concede nos projetos de permissões as permissões de `desired.platformPermissions` (o Executor não tem lista própria; sem o campo no `desired`, a ação é rejeitada sem retentativa). Antes disso consulta o `RESULT` para saber se aquele `actionId` já tem desfecho (idempotência).

| Item | Valor |
|---|---|
| Stream | `RESULT` (`LimitsPolicy`, `MaxAge`, `allow_direct`) |
| Subject | `executor.completed.core.account.<resourceId>.create` (ou `executor.failed...`) |

```json
{
  "messageId": "0199c8b3-4a00-7c2d-8e3f-4a5b6c7d8e06",
  "schemaVersion": "1.0",
  "messageType": "completed",
  "emitter": "executor",
  "module": "core",
  "resourceType": "account",
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
SELECT ... FROM core.account WHERE resource_id = %s FOR UPDATE;

INSERT INTO core.account_action_result (action_id, resource_id, desired_generation, action_outcome)
VALUES (%s, %s, %s, 'completed')
ON CONFLICT (action_id) DO NOTHING
RETURNING action_id;
```

Se o `INSERT` não devolver linha, o `actionId` já foi contabilizado e nada mais é feito (`DUPLICATE`). Se a `desiredGeneration` da mensagem não for a vigente, é ignorada (a especificação foi substituída). Senão:

```sql
UPDATE core.account
   SET failure_count = %s, phase = %s, reconciliation = %s, conditions = %s,
       resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = %s RETURNING resource_version;

UPDATE core.account_operation SET operation_status = 'in_progress', updated_at = now(),
       completed_at = CASE WHEN false THEN now() ELSE completed_at END
 WHERE resource_id = %s AND operation_status IN ('accepted','in_progress') AND desired_generation = %s;
```

Mais um `updated` no outbox. Para o `completed`: `failure_count` continua `0`, `phase = Reconciling` (se estava `Pending`), `resource_version = 3`. Para `failed`: `failure_count + 1`; ao chegar a **5 falhas na mesma geração**, `phase = Failed`, `reconciliation = suspended`, a Operation vira `failed` e o Manager republica o `desired` com `reconciliation: suspended` pelo outbox.

**`core.account_action_result`** (uma linha por resultado):

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
  "resourceType": "account",
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
    "accountState": "initial",
    "platformAccess": "granted",
    "platformPermissions": [
      "core.account.delete",
      "core.account.get",
      "sum.ipm.disable",
      "sum.ipm.enable",
      "sum.ipm.get"
    ]
  }
}
```

| Campo de `data` | Valores |
|---|---|
| `emailVerified` | `true` / `false` |
| `accountState` | `initial` enquanto a senha não foi definida; depois `active` ou `inactive` |
| `platformAccess` | `granted` se o usuário tem ao menos uma permissão no projeto; senão `revoked` |
| `platformPermissions` | Permissões que o usuário tem nos projetos de permissões, em ordem alfabética (inclui permissões a mais, como `core.account.admin` de um operador) |

O Manager aplica pela mesma sequência da seção 6.1. **Convergência** da Account: `presence = present`, `observed.platformAccess == desired.platformAccess` **e** `desired.platformPermissions ⊆ observed.platformPermissions` (permissões a mais não divergem; permissão faltando gera `update` com `reason = Drift`) **e** `observed.deletionProtection` igual à do `desired` (metadado do usuário, decisão 0074); `emailVerified` e `accountState` **não** entram na comparação. Convergiu, então:

| Onde | Valor final |
|---|---|
| `core.account.observed` | `{"emailVerified": false, "accountState": "initial", "platformAccess": "granted", "platformPermissions": ["core.account.delete", "core.account.get", "sum.ipm.disable", "sum.ipm.enable", "sum.ipm.get"]}` |
| `core.account.presence` / `observed_at` | `present` / `2026-10-09T14:00:05+00:00` |
| `core.account.phase` | `Ready` |
| `core.account.conditions` | `[{"type":"Ready","status":"True","reason":"Reconciled","observedGeneration":1,"lastTransitionAt":"2026-10-09T14:00:05+00:00"}]` |
| `core.account.resource_version` | `4` |
| `core.account_operation.operation_status` | `completed` (`completed_at` preenchido) |

Do ponto de vista dos dados, o cadastro termina aqui. A pessoa ainda precisa abrir o link do e-mail e definir a senha; isso não é gravado pelo SSOT até uma nova observação (`accountState` passa de `initial` a `active`, `emailVerified` a `true`, e `resource_version` sobe).

### 6.5 `updated`: o fato "mudou de fase"

A cada gravação do Manager que muda o estado observável (cada `observed` e cada resultado), ele grava no outbox uma mensagem `updated`, publicada depois pelo Publisher no Stream `UPDATED` (`LimitsPolicy`, `MaxAge`; consumida por console, auditoria e métricas).

Subject: `manager.updated.core.account.<resourceId>.changed`. Contrato do `data`: [`updated.v1.schema.json`](../../../../schemas/common/updated.v1.schema.json).

```json
{
  "messageId": "0199c8b3-6a00-7c2d-8e3f-4a5b6c7d8e08",
  "schemaVersion": "1.0",
  "messageType": "updated",
  "emitter": "manager",
  "module": "core",
  "resourceType": "account",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "causationId": "0199c8b3-5a00-7c2d-8e3f-4a5b6c7d8e07",
  "occurredAt": "2026-10-09T14:00:05+00:00",
  "publishedAt": "2026-10-09T14:00:05+00:00",
  "data": {
    "phase": "Ready",
    "lifecycle": "present",
    "resourceVersion": "4",
    "desiredGeneration": 1,
    "observedGeneration": 1
  }
}
```

Na remoção convergida, o `data` ganha `"removed": true`.

### 6.6 Linha do tempo do banco (cadastro bem-sucedido)

| Momento | `phase` | `resource_version` | `presence` | `failure_count` | `account_operation.operation_status` | Linhas novas no outbox |
|---|---|---|---|---|---|---|
| Passo 3 (`requested`) | `Pending` | 1 | `NULL` | 0 | `accepted` | `desired` |
| `observed` (`absent`) | `Reconciling` | 2 | `absent` | 0 | `in_progress` | `updated` |
| `completed` | `Reconciling` | 3 | `absent` | 0 | `in_progress` | `updated` |
| `observed` (`present`) | `Ready` | 4 | `present` | 0 | `completed` | `updated` |

A ordem entre `observed` e `completed` pode variar (são mensagens de Streams distintos); a tabela mostra a sequência típica. O resultado final não depende da ordem: `observed_at` nunca retrocede e `actionId` é contabilizado uma vez.

## 7. Leitura: `GET`

A API **nunca lê as tabelas**: só as views versionadas (decisão 0004), com o papel `core_account_receiver`, que tem `SELECT` apenas nelas.

| Rota | View | Quem lê |
|---|---|---|
| `GET /v1/core/accounts/{id}` | `core.account_v1` | O próprio usuário ou `core.account.admin`; outro usuário recebe `404` |
| `GET /v1/core/accounts/{id}/operations/{operationId}` | `core.account_operation_v1` | O solicitante ou `core.account.admin`; a Operation de cadastro anônimo só é legível por operadores |

`core.account_v1` expõe `resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation, resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at`, **sem `failure_count`**. `core.account_operation_v1` expõe as colunas de `core.account_operation` sem `correlation_id`; `requested_by` está nela só para o Receiver autorizar a leitura. O formato JSON devolvido está em [`schemas/core/account/resource.example.json`](../../../../schemas/core/account/resource.example.json) e [`schemas/common/operation.example.json`](../../../../schemas/common/operation.example.json).

Para conferir o banco no ambiente de dev (somente leitura, como o dono):

```sql
SELECT resource_id, phase, resource_version, presence, failure_count FROM core.account;
SELECT operation_id, operation_type, operation_status, operation_status_reason, desired_generation
  FROM core.account_operation ORDER BY created_at DESC;
SELECT sequence, subject, published_at FROM core.account_outbox ORDER BY sequence;
```

## 8. Remoção: `DELETE /v1/core/accounts/{id}?resourceVersion=`

**Proteção contra exclusão (decisões 0043, 0072 e 0074).** A conta nasce com `desired.deletionProtection = true`. `PATCH /v1/core/accounts/{id}` (corpo `{resourceVersion, deletionProtection}`, permissão `core.account.delete`, só a própria conta ou `core.account.admin`) publica `requested` com `operation = update` e `specification = {deletionProtection}`. A alteração percorre o loop como qualquer outra: o Manager grava o novo `desired` com nova geração, fase `Reconciling` e Operation `accepted`; o Reconciler vê a divergência com o metadado `deletionProtection` do usuário e decide `update`; o Executor grava o metadado; o Observer observa a nova geração e o `observed` conclui a Operation (`completed`, fase `Ready`) e gera o `updated` com `desiredGeneration` e `observedGeneration` iguais. O `DELETE` só segue com a proteção desligada.

Resumo dos dados (fluxo completo: [`08-remocao`](flow/08-remocao.mmd)). Exige token com a permissão `core.account.delete`; o dono ou `core.account.admin`. `resourceVersion` é obrigatório e deve ser o da última leitura (senão `409`). Aceita `Idempotency-Key` (o mesmo valor com outro conteúdo devolve `422`).

- **`requestDigest`:** SHA-256 de `{"operation":"delete","resourceId":"<id>","resourceVersion":"<versão>"}`.
- **`requested`:** subject `receiver.requested.core.account.<resourceId>.delete`; `requestedBy` = `sub` do token; `data = {operationId, requestDigest, resourceVersion}` (contrato: [`requested-delete.v1.schema.json`](../../../../schemas/core/account/requested-delete.v1.schema.json)).
- **Manager** (transação): `SELECT ... FOR UPDATE` na linha; se não existir, Operation `rejected/not_found`; se `resource_version` diferir, `rejected/conflict`; se `deletionProtection` for diferente de `false` (a conta nasce protegida; registro sem o campo vale como protegido), `rejected/protected` (decisão 0043; o Receiver já responde `409 DeletionProtected` antes). Calcula o novo `desired` **sem dados pessoais**: `{"lifecycle":"absent","platformAccess":"granted","platformPermissions":[...]}` (as permissões atuais são copiadas; nenhum dado pessoal). Grava:

```sql
UPDATE core.account
   SET lifecycle = 'absent', reconciliation = %s, desired = %s,
       desired_generation = desired_generation + 1, failure_count = 0,
       phase = 'Deleting', resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = %s AND resource_version = %s
RETURNING desired_generation;
```

  Mais `INSERT` na `core.account_operation` (`delete`, `accepted`, geração 2) e o `desired` no outbox.
- **Loop:** o Reconciler decide `delete` (motivo `DeletionRequested`); o Executor remove o usuário no Zitadel (ausente também é sucesso) e publica `completed`; o Observer observa `absent`.
- **Convergência:** o Manager marca a Operation como `completed`, executa `DELETE FROM core.account WHERE resource_id = %s` e grava um `updated` com `"removed": true`. As linhas de `core.account_operation`, `core.account_action_result` e `core.account_outbox` **permanecem** até a limpeza por retenção (papel `core_maintenance`, que só tem `SELECT`/`DELETE` nelas).

## 9. Mapa: quem grava o quê

| Mensagem recebida pelo Manager | `core.account` | `core.account_operation` | `core.account_action_result` | `core.account_outbox` |
|---|---|---|---|---|
| `requested` / `create` | `INSERT` (`Pending`, geração 1) | `INSERT` (`accepted`, ou `rejected`) | | `INSERT` `desired` |
| `requested` / `delete` | `UPDATE` (`absent`, geração +1, `Deleting`) | `INSERT` (`accepted`, ou `rejected`) | | `INSERT` `desired` |
| `observed` | `UPDATE` (observação, `conditions`, `phase`); `DELETE` se a remoção convergiu | `UPDATE` (`in_progress`, `completed`, ou `failed` nas gerações antigas) | | `INSERT` `updated` |
| `completed` / `failed` | `UPDATE` (`failure_count`, `phase`, `conditions`, `reconciliation`) | `UPDATE` (`in_progress`, ou `failed` ao suspender) | `INSERT` (uma vez por `actionId`) | `INSERT` `updated` (e `desired` suspenso no limite de falhas) |

| Papel de banco | Privilégio |
|---|---|
| `core_account_manager` | `SELECT`/`INSERT`/`UPDATE`/`DELETE` em `core.account`; `SELECT`/`INSERT`/`UPDATE` em `account_operation`; `SELECT`/`INSERT` em `account_action_result`; só `INSERT` em `account_outbox` |
| `core_account_receiver` | `SELECT` em `account_v1` e `account_operation_v1` |
| `core_account_publisher` | `SELECT` em `account_outbox` e `UPDATE (published_at)` |
| `core_maintenance` | `SELECT`/`DELETE` em `account_outbox`, `account_action_result` e `account_operation` |

Origem: bloco `GRANT` de [`migrations/0001-account.sql`](../migrations/0001-account.sql). O schema físico completo está em [`database/01-er-fisico.mmd`](database/01-er-fisico.mmd).

> **Atenção ao ler o diagrama físico.** O ER físico usa nomes como `core_account_operation` e `core_account_outbox`, e descreve `operation_type` como "create ou delete (sem update)". A migração cria `core.account_operation` e `core.account_outbox` (schema `core`, tabela `account_...`) e o seu `CHECK` aceita também `'update'`. Em caso de divergência, vale a migração.
