# PostgreSQL

# 1. Introdução

Este documento define a implementação de referência do SSOT em PostgreSQL, com `jsonb` para o conteúdo declarativo. O modelo, as invariantes e as garantias são definidos exclusivamente em `SSOT.md`.

PostgreSQL é uma tecnologia de armazenamento. Este documento descreve como o modelo lógico é materializado em banco, schemas, tabelas, views, colunas, restrições, privilégios e rotinas de manutenção.

```text
SSOT.md
    |
    v
POSTGRESQL.md
```

# 2. Objetivos

Estabelecer uma implementação PostgreSQL consistente, previsível, segura e resiliente das garantias de `SSOT.md`:
- unidade atômica de gravação de admissão pela API e de reconciliação pelo Controller;
- concorrência otimista para o solicitante via `resource_version`;
- serialização pessimista por bloqueio de linha (`SELECT ... FOR UPDATE`);
- deduplicação idempotente de requisições de admissão por solicitante (`<tipo>_idempotency`);
- outbox transacional estritamente ordenado por recurso;
- privilégios mínimos segregados por papel de banco (`api`, `controller`, `publisher`, `maintenance`);
- rotina de retenção operacional de 24 horas via utilitário dedicado;
- evolução segura por migrações e recuperação testada a um ponto no tempo.

# 3. Princípios de implementação

- **Respeitar o modelo.** Uma limitação do PostgreSQL não altera `SSOT.md`; a adaptação permanece confinada a este documento.
- **Recursos nativos.** Usar apenas recursos do núcleo do PostgreSQL. Nenhuma extensão proprietária é obrigatória.
- **Dois escritores segregados.** A API grava a intenção declarativa e o outbox de `desired`; o Controller grava a observação, as condições de convergência e o outbox de `updated` (`SSOT.md` §4).
- **Atomicidade transacional.** O recurso e a mensagem correspondente no outbox são gravados na mesma transação. Nunca existe alteração persistida sem respectivo registro no outbox.
- **Desacoplamento por views.** A leitura por clientes e consultas é intermediada por views versionadas (`<tipo>_v<MAJOR>`).
- **Privilégios mínimos.** Nenhuma credencial de aplicação possui privilégios de DDL (`CREATE`, `ALTER`, `DROP`) ou privilégios desnecessários sobre tabelas alheias à sua função.
- **Documentação viva.** Versão do PostgreSQL, configurações e comportamentos descritos são verificados periodicamente no ambiente real da plataforma.

# 4. Contexto e escopo

| Elemento | Definição na Plataforma |
|---|---|
| SGBD | **PostgreSQL 18.6** (versão de referência do ambiente de desenvolvimento) |
| Banco | `ssot` (banco único consolidado de recursos gerenciados, decisão 0087) |
| Schemas | Um schema por módulo funcional da plataforma (`ipm`, `core`, `bsm`, `sum`, etc.) |
| Tabelas | Três por tipo de recurso: `<tipo>`, `<tipo>_outbox` e `<tipo>_idempotency` (decisões 0096, 0098, 0101) |
| Views | Uma por tipo de recurso para a interface de leitura da API: `<tipo>_v<MAJOR>` |
| Papéis | `<módulo>_<tipo>_api`, `<módulo>_<tipo>_controller`, `<módulo>_<tipo>_publisher` e `<módulo>_maintenance` |

As tabelas e as views de cada tipo de recurso seguem **um único modelo arquitetural** (o DDL de referência da seção 6.4) adaptado ao contrato do recurso (`SCHEMA.md`).

# 5. Arquitetura de armazenamento

A estrutura física no PostgreSQL isola os módulos por schemas e segrega o acesso por papéis de função:

```text
Banco: ssot
  ├── Schema: ipm
  │     ├── Tabela: organization
  │     ├── Tabela: organization_outbox
  │     ├── Tabela: organization_idempotency
  │     └── View:   organization_v1
  ├── Schema: core
  │     ├── Tabela: account
  │     ├── Tabela: account_outbox
  │     ├── Tabela: account_idempotency
  │     └── View:   account_v1
  └── Schema: ...
```

Cada serviço conecta-se ao banco através de um papel de login específico, herdando estritamente os privilégios do papel funcional correspondente.

# 6. Estrutura das tabelas

## 6.1 Tabela `<tipo>` (Resource)

Armazena o estado consolidado de cada recurso (um registro por `resource_id`):

- **Identidade e Versionamento:** `resource_id` (PK, texto formatado em UUIDv7), `schema_version` (`MAJOR.MINOR`), `desired_generation` (inteiro crescente >= 1), `resource_version` (inteiro crescente para controle otimista);
- **Intenção Declarativa:** `lifecycle` (`present`, `absent`), `reconciliation` (`active`, `suspended`), `desired` (`jsonb` com limite de 256 KiB);
- **Rastreabilidade e Causa:** `requested_by` (identificador do solicitante da geração vigente), `correlation_id` (identificador do fluxo de rastreamento);
- **Observação e Realidade:** `observed` (`jsonb`), `presence` (`present`, `absent`, `unknown`), `observed_at` (`timestamptz`);
- **Convergência e Status:** `phase` (`Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting`), `conditions` (`jsonb array`), `failure_count` (inteiro >= 0), `observed_generation` (inteiro crescente);
- **Auditoria Temporal:** `created_at` e `updated_at` (`timestamptz`).

`lifecycle`, `reconciliation`, `presence` e `phase` são colunas dedicadas (e não campos dentro do `jsonb`) porque participam ativamente de regras de validação (`CHECK`), filtros de reconciliação e controle de concorrência.

## 6.2 Tabela `<tipo>_idempotency`

Armazena a deduplicação de requisições de admissão submetidas pelo cliente com o cabeçalho `Idempotency-Key` (`SSOT.md` §7.2, decisão 0098):

- `requested_by` (texto, parte da chave primária composta: a chave é rigorosamente escopada ao solicitante autenticado);
- `idempotency_key` (texto, fornecida pelo cliente);
- `request_digest` (texto, hash criptográfico SHA-256 do corpo canônico da requisição);
- `resource_id` (texto, identificador do recurso admitido);
- `created_at` (`timestamptz`, instante de criação, com índice para a rotina de expurgo).

A chave primária composta `(requested_by, idempotency_key)` garante unicidade física por solicitante. Registros com mais de 24 horas são expurgados pelo utilitário de retenção.

## 6.3 Tabela `<tipo>_outbox`

Armazena a fila transacional de mensagens aguardando entrega ao NATS JetStream pelo Publisher (`SSOT.md` §7.3, decisões 0019, 0101):

- `sequence` (`bigint GENERATED ALWAYS AS IDENTITY`, PK, ordem de inserção na transação);
- `message_id` (texto, UUIDv7 único, chave de deduplicação no transporte NATS);
- `resource_id` (texto, recurso associado);
- `subject` (texto, Subject canônico de 4 tokens: `<messageType>.<module>.<resourceType>.<resourceId>`);
- `payload` (`jsonb`, envelope completo da mensagem conforme `schemas/common/message-envelope.v1.schema.json`, limite de 256 KiB);
- `created_at` (`timestamptz`, instante em que a transação comitou a mensagem);
- `published_at` (`timestamptz`, nulo enquanto pendente; preenchido pelo Publisher após confirmação do broker);
- `traceparent` (texto de 55 caracteres, opcional: contexto W3C Trace Context propagado pelo Publisher).

Índices parciais aceleram as duas operações do outbox:
1. `WHERE published_at IS NULL`: varredura de mensagens pendentes pelo Publisher;
2. `WHERE published_at IS NOT NULL`: expurgo de mensagens publicadas pela rotina de retenção.

## 6.4 Views de leitura da API (`<tipo>_v<MAJOR>`)

A API atende consultas e listagens através de views versionadas (ex: `<tipo>_v1`), que formam a **interface de leitura desacoplada** do SSOT:

- expõe apenas as colunas públicas do contrato (`resource_id`, `schema_version`, `lifecycle`, `reconciliation`, `desired`, `desired_generation`, `resource_version`, `observed`, `presence`, `observed_at`, `phase`, `conditions`, `created_at`, `updated_at`);
- oculta colunas internas de controle operacional (como `failure_count`);
- executa com privilégios de proprietário, permitindo conceder privilégios de `SELECT` na view sem expor acesso de consulta direta à tabela base.

## 6.5 DDL de referência

Modelo de referência físico para um tipo de recurso (`sample.item`):

```sql
CREATE SCHEMA sample;

CREATE TABLE sample.item (
  resource_id         text        PRIMARY KEY
                      CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  schema_version      text        NOT NULL CHECK (schema_version ~ '^[0-9]+\.[0-9]+$'),
  lifecycle           text        NOT NULL CHECK (lifecycle IN ('present', 'absent')),
  reconciliation      text        NOT NULL DEFAULT 'active' CHECK (reconciliation IN ('active', 'suspended')),
  desired             jsonb       NOT NULL
                      CHECK (jsonb_typeof(desired) = 'object' AND pg_column_size(desired) <= 262144),
  desired_generation  bigint      NOT NULL CHECK (desired_generation >= 1),
  resource_version    bigint      NOT NULL DEFAULT 1,
  observed            jsonb
                      CHECK (observed IS NULL OR (jsonb_typeof(observed) = 'object' AND pg_column_size(observed) <= 262144)),
  presence            text        CHECK (presence IN ('present', 'absent', 'unknown')),
  observed_at         timestamptz,
  phase               text        NOT NULL CHECK (phase IN ('Pending', 'Reconciling', 'Ready', 'Failed', 'Deleting')),
  conditions          jsonb       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(conditions) = 'array'),
  failure_count       integer     NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  observed_generation bigint,
  requested_by        text        CHECK (length(requested_by) BETWEEN 1 AND 256),
  correlation_id      text        CHECK (length(correlation_id) BETWEEN 1 AND 256),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CHECK ((presence IS NULL) = (observed_at IS NULL)),
  CHECK (observed_generation IS NULL
         OR (observed_generation >= 1 AND observed_generation <= desired_generation))
);

CREATE TABLE sample.item_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 256),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX item_idempotency_retention ON sample.item_idempotency (created_at);

CREATE TABLE sample.item_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  traceparent  text        CHECK (traceparent IS NULL OR length(traceparent) = 55)
);
CREATE INDEX item_outbox_pending   ON sample.item_outbox (sequence)     WHERE published_at IS NULL;
CREATE INDEX item_outbox_published ON sample.item_outbox (published_at) WHERE published_at IS NOT NULL;

CREATE VIEW sample.item_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM sample.item;
```

# 7. JSONB

## 7.1 O que é `jsonb` e o que é coluna

| `jsonb` | Coluna dedicada |
|---|---|
| `desired` (conteúdo declarativo de especificação) | `resource_id`, `schema_version` |
| `observed` (leitura estruturada do provedor externo) | `lifecycle`, `reconciliation`, `phase`, `presence` |
| `conditions` (lista de condições da convergência) | `desired_generation`, `observed_generation`, `resource_version` |
| `payload` (envelope completo de mensagem no outbox) | `failure_count`, `requested_by`, `correlation_id`, `observed_at` |

`jsonb` não substitui a modelagem relacional: não se usa `jsonb` para evitar uma coluna que participe ativamente de integridade, restrições, concorrência ou filtros frequentes do loop.

## 7.2 Propriedades do `jsonb` no PostgreSQL

- `jsonb` **não preserva a ordem das chaves nem os espaços**, mantém **apenas a última ocorrência de chave duplicada** e **normaliza a representação numérica** (ex: `1.0` e `1.00` são idênticos). Isso viabiliza a comparação semântica entre estados declarativos, mas impede o cálculo de assinaturas ou digests diretamente a partir do texto do `jsonb`;
- `jsonb` rejeita caracteres nulos (`\u0000`), `NaN` e infinito, bem como números fora da faixa de precisão de `numeric`;
- o banco deve operar obrigatoriamente com codificação UTF-8;
- toda atualização em um registro bloqueia a linha inteira. Documentos pequenos e focados reduzem a contenção de I/O e a sobrecarga de MVCC.

## 7.3 Comparação semântica e avanço de geração

A comparação de igualdade entre objetos `jsonb` é semântica e independe da ordem de serialização das chaves. Na admissão da API, a geração do estado desejado (`desired_generation`) só é incrementada se o conteúdo declarativo de especificação tiver mudado:

```sql
desired_generation = desired_generation
  + (CASE WHEN desired IS DISTINCT FROM $novo_desired THEN 1 ELSE 0 END)
```

Alterações que modifiquem apenas o controle operacional (como `reconciliation = suspended`) não incrementam `desired_generation`.

## 7.4 Índices

Nenhum índice GIN é criado por padrão nas tabelas do SSOT. O acesso pelo loop e pela API é estritamente indexado por `resource_id` (PK) e por chaves relacionais específicas definidas no contrato do recurso (por exemplo, índices únicos parciais sobre nomes amigáveis ou vínculos ativos).

# 8. Transações e isolamento

- O nível de isolamento adotado é **Read Committed** (padrão do PostgreSQL). Níveis mais restritivos (como Serializable) provocariam falhas de serialização sob alta concorrência e são desnecessários, pois a serialização de acesso ao mesmo recurso é assegurada pelo bloqueio exclusivo de linha;
- Cada admissão pela API e cada ciclo de reconciliação pelo Controller constitui **uma transação atômica única**;
- Toda transação de escrita sobre um recurso existente inicia **bloqueando a sua linha com `FOR UPDATE`**:

```sql
SELECT resource_version, desired_generation, desired, reconciliation, observed_at,
       phase, conditions, failure_count
  FROM sample.item
 WHERE resource_id = $id
   FOR UPDATE;
```

Em Read Committed, um comando aguarda a liberação do bloqueio de transações concorrentes sobre a mesma linha e, ao obter a posse, enxerga os dados mais recentes já comitados. Isso garante que ciclos paralelos de reconciliação ou requisições concorrentes de clientes nunca processem sobre estados defasados.

- Na criação inicial, a inexistência da linha é resolvida pela tentativa atômica de `INSERT`. Entregas concorrentes disputam a chave primária `resource_id` ou o índice único de unicidade: a perdedora falha com erro de chave duplicada (`23505`), sendo tratada pela API como conflito (`409 Conflict`) ou resolvida pela tabela de idempotência;
- A linha do recurso é atualizada **antes da inserção da mensagem correspondente no outbox**, garantindo que a ordem de sequência do outbox coincida com a ordem de comit das transações por recurso.

# 9. Concorrência otimista

A concorrência otimista protege as alterações submetidas por solicitantes via API (`SSOT.md` §11). Em requisições de alteração (`PATCH` ou `DELETE`), a API valida a versão fornecida pelo cliente (`If-Match` ou `resourceVersion`):

```sql
UPDATE sample.item
   SET desired            = $desired,
       desired_generation = desired_generation
                          + (CASE WHEN desired IS DISTINCT FROM $desired THEN 1 ELSE 0 END),
       failure_count      = CASE WHEN desired IS DISTINCT FROM $desired THEN 0 ELSE failure_count END,
       requested_by       = $requested_by,
       correlation_id     = $correlation_id,
       resource_version   = resource_version + 1,
       updated_at         = now()
 WHERE resource_id = $id
   AND resource_version = $versao_informada
RETURNING desired_generation, resource_version;
```

Se o comando retornar zero linhas afetadas sobre um recurso cuja existência já foi constatada sob bloqueio, significa que uma alteração concorrente modificou o recurso previamente. A transação é revertida e a API responde HTTP `409 Conflict`.

# 10. Idempotência

## 10.1 Admissão síncrona pela API

A deduplicação de requisições de admissão é gerenciada pela tabela `<tipo>_idempotency` (`SSOT.md` §7.2, §12):

1. Ao receber uma requisição com o cabeçalho `Idempotency-Key`, a API calcula o digest criptográfico (SHA-256) do corpo canônico da requisição;
2. Sob a transação de admissão, consulta a chave para o solicitante autenticado:

```sql
SELECT request_digest, resource_id
  FROM sample.item_idempotency
 WHERE requested_by = $requested_by
   AND idempotency_key = $idempotency_key;
```

3. Se o registro existir:
   - se `request_digest == $digest`: a requisição é uma repetição idêntica. A API desfaz a transação e consulta a view `<tipo>_v1` pelo `resource_id` já gravado, devolvendo o estado atual com HTTP `200 OK` (ou `201 Created`);
   - se `request_digest != $digest`: a mesma chave foi reutilizada com payload divergente. A transação reverte e a API responde HTTP `422 IdempotencyKeyReused`.
4. Se o registro não existir, a API insere a linha na tabela de idempotência, insere ou atualiza o recurso na tabela principal, grava a mensagem `desired` no outbox e comita a transação:

```sql
INSERT INTO sample.item_idempotency
       (requested_by, idempotency_key, request_digest, resource_id)
VALUES ($requested_by, $idempotency_key, $request_digest, $resource_id);
```

## 10.2 Reconciliação pelo Controller

O Controller não utiliza tabelas de idempotência nem guarda histórico de ações passadas (decisão 0096). A idempotência é intrínseca ao ciclo de reconciliação:

1. O Controller abre transação e adquire bloqueio da linha (`SELECT ... FOR UPDATE`);
2. Observa a realidade factual do sistema externo;
3. Se a realidade coincidir com o `desired`, nenhuma ação externa é executada (convergência atingida);
4. Se houver discrepância, executa a ação externa de forma idempotente (utilizando chaves de correlação ou identificadores determinísticos no provedor externo);
5. Reobserva imediatamente o sistema externo para confirmar a realidade;
6. Atualiza o recurso no SSOT garantindo a monotonicidade de `observed_at`:

```sql
UPDATE sample.item
   SET observed            = $observed,
       presence            = $presence,
       observed_at         = $observed_at,
       conditions          = $conditions,
       phase               = $phase,
       observed_generation = GREATEST(observed_generation, $geracao_confirmada),
       resource_version    = resource_version + 1,
       updated_at          = now()
 WHERE resource_id = $id
   AND (observed_at IS NULL OR observed_at <= $observed_at);
```

Se `observed_at` for mais antigo que a observação já persistida, a atualização é descartada sem erro.

# 11. Outbox e Publisher

O **Publisher** é um processo dedicado de menor privilégio responsável pela entrega de mensagens do outbox ao broker NATS JetStream (decisão 0019). O outbox é o contrato desacoplado entre os escritores do SSOT (API e Controller) e o Publisher.

## 11.1 Gravação

A mensagem é inserida na tabela `<tipo>_outbox` **na mesma transação** da alteração de estado no SSOT:

```sql
INSERT INTO sample.item_outbox (message_id, resource_id, subject, payload, traceparent)
VALUES ($message_id, $id, $subject, $payload, $traceparent);
```

O `subject` obedece estritamente ao formato canônico de 4 tokens (`desired.<mod>.<type>.<id>` ou `updated.<mod>.<type>.<id>`, decisão 0101).

## 11.2 Ordem estrita por recurso

O campo `sequence` é atribuído sequencialmente pelo PostgreSQL. Como a transação adquire previamente o bloqueio exclusivo da linha do recurso (`FOR UPDATE`), **duas transações sobre o mesmo recurso são estritamente serializadas**: a segunda só insere no outbox após o comit da primeira. Portanto, para qualquer recurso individual, a ordem de `sequence` reflete com exatidão a ordem cronológica de confirmação de suas alterações.

## 11.3 Varredura sem marca-d'água

O Publisher realiza varredura periódica do outbox selecionando mensagens pendentes:

```sql
SELECT sequence, message_id, subject, payload, traceparent
  FROM sample.item_outbox
 WHERE published_at IS NULL
 ORDER BY sequence
 LIMIT $lote;
```

A seleção utiliza o índice parcial `WHERE published_at IS NULL`. Não se utiliza cursor ou marca-d'água sequencial: transações concorrentes sobre recursos diferentes podem comitar fora da ordem de atribuição de `sequence`. Filtrar por `published_at IS NULL` assegura que nenhuma mensagem comitada tardiamente seja ignorada.

## 11.4 Exclusão mútua por trava consultiva

Para assegurar ordem estrita de entrega, **apenas uma instância ativa do Publisher opera por tabela de outbox**, coordenada por trava consultiva de sessão no PostgreSQL:

```sql
SELECT pg_try_advisory_lock(hashtext('sample.item_outbox'));
```

- A trava é mantida durante toda a vida da sessão de publicação e liberada automaticamente em caso de queda ou encerramento, permitindo *failover* imediato para instâncias reservas em espera;
- Antes de processar cada lote, o Publisher confirma que ainda mantém a posse da trava;
- **`FOR UPDATE SKIP LOCKED` é vedado no outbox ordenado:** o mecanismo faria uma segunda instância pular mensagens retidas e publicar alterações posteriores fora de ordem.

## 11.5 Publicação sequencial e confirmação

A publicação é estritamente sequencial:

1. O Publisher publica a mensagem no NATS, incluindo `message_id` no cabeçalho `Nats-Msg-Id` para deduplicação transparente no broker;
2. Aguarda a confirmação de persistência do JetStream (ACK) antes de prosseguir com a próxima mensagem;
3. Após a confirmação, atualiza `published_at` no banco:

```sql
UPDATE sample.item_outbox
   SET published_at = now()
 WHERE sequence = ANY($sequences);
```

Se a publicação falhar, o lote é interrompido e as mensagens pendentes são retentadas com recuo exponencial.

# 12. Retenção operacional

O SSOT não acumula mensagens publicadas nem registros de idempotência indefinidamente. A retenção operacional adota uma **janela padrão de 24 horas** (decisão 0101):

| Tabela | Critério de Expurgação |
|---|---|
| `<tipo>_outbox` | Mensagens já confirmadas no broker: `published_at IS NOT NULL AND published_at < cutoff` |
| `<tipo>_idempotency` | Requisições concluídas: `created_at < cutoff` |

A expurgo é executado periodicamente pelo utilitário `scripts/dev/retention` (imagem `smarkee-dev-retention` em contêiner), operando sob credencial de manutenção restrita (`<módulo>_maintenance_login`).

Nenhum papel de serviço de runtime (`api`, `controller`, `publisher`) possui permissão de `DELETE` sobre as tabelas de outbox ou idempotência.

# 13. Remoção de recursos

A remoção de um recurso obedece ao ciclo declarativo de convergência (`SSOT.md` §14):

1. **Pedido de exclusão:** a API atualiza a linha do recurso marcando `lifecycle = 'absent'`, `phase = 'Deleting'` e insere a mensagem `desired` no outbox;
2. **Reconciliação:** o Controller detecta `lifecycle = 'absent'`, executa a remoção física no sistema externo e reobserva até constatar `presence = 'absent'`;
3. **Convergência factual:** sob a mesma transação com bloqueio exclusivo, o Controller executa o `DELETE` físico da linha do recurso no SSOT e insere no outbox a mensagem `updated` com `data.removed = true`:

```sql
DELETE FROM sample.item WHERE resource_id = $id;

INSERT INTO sample.item_outbox (message_id, resource_id, subject, payload)
VALUES ($message_id, $id, 'updated.sample.item.' || $id, $payload_removed);
```

# 14. Segurança

## 14.1 Proteção no nível do banco de dados

O banco de dados `ssot` é gerenciado com o proprietário administrativo `ssot`. Por padrão, privilégios públicos permissivos são revogados:

```sql
REVOKE ALL ON DATABASE ssot FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
```

Acesso de conexão (`CONNECT`) é concedido explicitamente apenas aos papéis de login autorizados.

## 14.2 Matriz de privilégios por papel de banco

Os privilégios aplicam estritamente o princípio do menor privilégio (`RESOURCE-CONTROL-SECURITY.md`):

| Papel | Objeto | Privilégios Concedidos | Justificativa |
|---|---|---|---|
| `<módulo>_<tipo>_api` | `<tipo>` | `SELECT, INSERT, UPDATE` | Admissão, concorrência otimista e consulta direta |
| | `<tipo>_v<MAJOR>` | `SELECT` | Atendimento a leituras e listagens públicas |
| | `<tipo>_idempotency` | `SELECT, INSERT` | Deduplicação de requisições por solicitante |
| | `<tipo>_outbox` | `INSERT` | Gravação de mensagens `desired` |
| `<módulo>_<tipo>_controller` | `<tipo>` | `SELECT, UPDATE, DELETE` | Ciclo sob `FOR UPDATE`, observação e remoção física |
| | `<tipo>_outbox` | `INSERT` | Gravação de mensagens `updated` e `desired` suspenso |
| `<módulo>_<tipo>_publisher` | `<tipo>_outbox` | `SELECT, UPDATE (published_at)` | Varredura e marcação de envio |
| `<módulo>_maintenance` | `<tipo>_outbox` | `SELECT, DELETE` | Expurgação de retenção de mensagens confirmadas |
| | `<tipo>_idempotency` | `SELECT, DELETE` | Expurgação de requisições de admissão antigas |
| `ssot` | Todos | Dono (`OWNER`) | Migrações DDL e rotinas administrativas |

DDL de concessão de privilégios para o tipo de referência:

```sql
GRANT CONNECT ON DATABASE ssot TO sample_item_api, sample_item_controller, sample_item_publisher, sample_maintenance;

REVOKE ALL ON SCHEMA sample FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA sample FROM PUBLIC;
GRANT USAGE ON SCHEMA sample TO sample_item_api, sample_item_controller, sample_item_publisher, sample_maintenance;

-- Papel da API (admissão e leitura)
GRANT SELECT, INSERT, UPDATE ON sample.item             TO sample_item_api;
GRANT SELECT                 ON sample.item_v1          TO sample_item_api;
GRANT SELECT, INSERT         ON sample.item_idempotency TO sample_item_api;
GRANT INSERT                 ON sample.item_outbox      TO sample_item_api;

-- Papel do Controller (reconciliação externa)
GRANT SELECT, UPDATE, DELETE ON sample.item             TO sample_item_controller;
GRANT INSERT                 ON sample.item_outbox      TO sample_item_controller;

-- Papel do Publisher (entrega de mensageria)
GRANT SELECT                ON sample.item_outbox TO sample_item_publisher;
GRANT UPDATE (published_at) ON sample.item_outbox TO sample_item_publisher;

-- Papel de Manutenção (retenção operacional)
GRANT SELECT, DELETE ON sample.item_outbox, sample.item_idempotency TO sample_maintenance;
```

Destaques da separação de privilégios:
- A API **não possui `DELETE`** na tabela principal do recurso e não possui permissão de leitura sobre o outbox;
- O Controller **não acessa a tabela de idempotência** e não altera campos de admissão de `desired`;
- O Publisher acessa exclusivamente a tabela de outbox, com escrita restrita à coluna `published_at`;
- Nenhum papel de serviço em runtime (`api`, `controller`, `publisher`) possui permissão de `DELETE` sobre o outbox ou idempotência;
- Nenhum papel de serviço em runtime possui privilégios de DDL (`CREATE`, `ALTER`, `DROP`).

## 14.3 Parâmetros de sessão por papel de login

Parâmetros de configuração de sessão são atribuídos aos papéis de login (`*_login`) para limitar retenção de travas e forçar resolução explícita de nomes:

```sql
ALTER ROLE <servico_login> SET search_path = '';
ALTER ROLE <servico_login> SET lock_timeout = '2s';
ALTER ROLE <servico_login> SET statement_timeout = '5s';
ALTER ROLE <servico_login> SET idle_in_transaction_session_timeout = '10s';
```

- `search_path = ''` impede ataques de sombreamento de objetos e força o uso de nomes qualificados (`sample.item`);
- `lock_timeout = '2s'` encerra consultas bloqueadas por contenção excessiva com erro `55P03`;
- `idle_in_transaction_session_timeout = '10s'` desfaz transações que mantenham bloqueios abertos de forma inativa;
- O papel do Publisher não utiliza `idle_session_timeout` para permitir a preservação da trava consultiva de sessão durante períodos de ociosidade do barramento.

## 14.4 Segredos e dados confidenciais

- Credenciais de acesso ao banco são injetadas exclusivamente por variáveis de ambiente a partir do cofre de segredos da plataforma;
- Senhas, hashes de senhas ou chaves criptográficas privadas **nunca são armazenadas no SSOT** em texto puro;
- Colunas e propriedades marcadas como confidenciais no contrato (`x-sensitivity: confidential`) são mascaradas em traces, logs e mensagens de erro do PostgreSQL.

# 15. Migrações

- As migrações são arquivos SQL versionados, mantidos na pasta `migrations/` de cada feature (ex: `features/ipm/organization/migrations/`);
- São executadas exclusivamente pelo papel administrativo `ssot` durante etapas automatizadas de deploy em pipelines de CI/CD;
- A evolução do schema obedece à estratégia **expandir → migrar → contrair**:
  1. *Expandir:* adição de novas colunas ou novas views versionadas de forma compatível;
  2. *Migrar:* transição das aplicações para o novo formato;
  3. *Contrair:* remoção de colunas ou views depreciadas após encerramento do período de coexistência;
- As views de leitura versionadas (`<tipo>_v<MAJOR>`) protegem os clientes contra mudanças estruturais internas nas tabelas base.

# 16. Backup e recuperação

- A plataforma requer rotina de cópia de segurança contínua com recuperação a um ponto no tempo (**PITR - Point-in-Time Recovery**), combinando backups base periódicos e arquivamento de WALs fora do nó de banco de dados;
- A restauração deve ser testada e validada periodicamente em ambiente isolado.

## 16.1 Procedimento de recuperação pós-restauração

Caso o banco seja restaurado a um ponto no tempo anterior (com serviços pausados):

1. Limpar mensagens não publicadas do outbox anteriores ao ponto restaurado:
   ```sql
   DELETE FROM sample.item_outbox WHERE published_at IS NULL;
   ```
2. Para cada recurso, consultar no Stream `DESIRED` do NATS JetStream o último estado publicado;
3. Se a geração retida no transporte for maior ou igual com conteúdo diferente, atualizar `desired_generation` no SSOT para a geração do transporte + 1 e gravar a nova mensagem no outbox;
4. Identificar recursos retidos no NATS que não constem no backup restaurado;
5. Retomar a operação normal dos serviços.

# 17. Alta disponibilidade

- O banco `ssot` opera com réplicas e failover gerenciado pela infraestrutura;
- A replicação para failover automático deve ser síncrona para evitar perda de transações confirmadas com mensagens já entregues ao transporte;
- Durante indisponibilidade temporária do banco, a API responde `503 Service Unavailable` com cabeçalho `Retry-After: 5`, e o Controller suspende os ciclos de reconciliação.

# 18. Observabilidade

Métricas e sinais monitorados sem exposição de dados confidenciais:

- Quantidade e idade da mensagem pendente mais antiga no outbox (`outbox_oldest_age_seconds`);
- Taxa de requisições de admissão com conflito de concorrência (`409 Conflict`);
- Taxa de reuso inválido de chaves de idempotência (`422 IdempotencyKeyReused`);
- Ocorrências de `lock_timeout` (`55P03`) e esperas excessivas por bloqueio de linha em `sample.item`;
- Taxa de lotes de publicação do Publisher interrompidos por falha de transporte;
- Quantidade de registros expurgados pela rotina de retenção de 24 horas;
- Distribuição de recursos por fase (`Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting`).

# 19. Anti-padrões

- Escrever no banco de dados através de componentes não autorizados (somente a API e o Controller do respectivo tipo escrevem no SSOT);
- Gravar alterações no recurso sem registrar a respectiva mensagem no outbox na mesma transação atômica;
- Executar leitura e alteração de estado no Controller sem adquirir previamente o bloqueio exclusivo da linha (`SELECT ... FOR UPDATE`);
- Utilizar `FOR UPDATE SKIP LOCKED` na varredura do outbox ordenado;
- Publicar mensagens do outbox em paralelo ou sem confirmação (ACK) sequencial do JetStream;
- Tentar publicar diretamente no NATS dentro do processo da API sem utilizar o outbox transacional;
- Utilizar marca-d'água de sequência para varredura do outbox;
- Permitir que papéis de serviço de runtime executem comandos de DDL (`CREATE`, `ALTER`, `DROP`);
- Conceder permissão de `DELETE` no outbox ou na tabela de idempotência para papéis de runtime;
- Armazenar segredos ou credenciais em texto puro dentro de campos `jsonb`.

# 20. Checklist de conformidade

- [ ] O banco `ssot` é a fonte exclusiva de recursos gerenciados, sem privilégios para `PUBLIC`?
- [ ] O tipo de recurso possui apenas as 3 tabelas autorizadas (`<tipo>`, `<tipo>_outbox`, `<tipo>_idempotency`) e a view de leitura `<tipo>_v1`?
- [ ] Colunas de controle (`lifecycle`, `reconciliation`, `presence`, `phase`) possuem validações `CHECK` adequadas?
- [ ] O tamanho do conteúdo `desired` e do envelope no outbox é limitado a 256 KiB?
- [ ] Toda transação de escrita sobre recurso existente inicia com `FOR UPDATE` na linha?
- [ ] A admissão de alteração do cliente confere `resource_version` e rejeita conflitos com HTTP 409?
- [ ] A idempotência de admissão utiliza a tabela `<tipo>_idempotency` escopada por `requested_by`?
- [ ] O Publisher opera com exclusão mútua via trava consultiva de sessão e publica de forma sequencial com confirmação?
- [ ] A rotina de retenção operacional expurga mensagens de outbox e registros de idempotência com mais de 24 horas via papel de manutenção?
- [ ] As credenciais de runtime possuem privilégios mínimos estritamente configurados conforme a matriz de segurança?

# 21. Verificação do DDL de referência

O DDL, as restrições de integridade, os privilégios e os comportamentos transacionais descritos neste documento foram validados no banco `ssot` do ambiente de desenvolvimento da plataforma (**PostgreSQL 18.6**):

- criação isolada por schemas e revogação de acessos padrão de `PUBLIC`;
- restrições de integridade (`CHECK`) sobre identificadores UUIDv7, estados do ciclo de vida e coerência entre `presence` e `observed_at`;
- concorrência otimista com rejeição de versões desatualizadas de `resource_version`;
- avanço estrito de `desired_generation` condicionado à alteração semântica do `desired`;
- monotonicidade temporal de `observed_at` em reconciliações concorrentes;
- serialização pessimista com `FOR UPDATE` e visibilidade consistente em Read Committed;
- deduplicação de requisições de admissão pela tabela de idempotência por solicitante;
- integridade do outbox transacional ordenado por recurso e exclusão mútua por trava consultiva de sessão no Publisher;
- isolamento rigoroso de privilégios entre os papéis `api`, `controller`, `publisher` e `maintenance`.

# 22. Fontes técnicas

- Tipos JSON no PostgreSQL: https://www.postgresql.org/docs/current/datatype-json.html
- Níveis de Isolamento de Transação: https://www.postgresql.org/docs/current/transaction-iso.html
- Bloqueio Explícito e Cláusulas de Bloqueio: https://www.postgresql.org/docs/current/explicit-locking.html
- Travas Consultivas (Advisory Locks): https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS
- Cláusula `ON CONFLICT`: https://www.postgresql.org/docs/current/sql-insert.html
- Views e Segurança: https://www.postgresql.org/docs/current/sql-createview.html
- Privilégios e Comandos GRANT/REVOKE: https://www.postgresql.org/docs/current/ddl-priv.html
- Parâmetros de Configuração de Sessão: https://www.postgresql.org/docs/current/runtime-config-client.html

# 23. Fonte de verdade

`SSOT.md` é a fonte de verdade do modelo lógico e das garantias de gravação.

`POSTGRESQL.md` é a fonte de verdade da **implementação física dessas garantias em PostgreSQL**.

```text
SSOT.md
    |
    v
POSTGRESQL.md
```
