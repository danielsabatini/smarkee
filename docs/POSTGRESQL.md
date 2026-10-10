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

Estabelecer uma implementação PostgreSQL consistente, previsível, segura e resiliente das garantias de `SSOT.md`: unidade atômica de gravação por mensagem com acesso exclusivo ao registro, concorrência otimista para o solicitante, idempotência semântica, outbox ordenado por recurso, privilégios mínimos, migração segura e recuperação a um ponto no tempo.

# 3. Princípios de implementação

- **Respeitar o modelo.** Uma limitação do PostgreSQL não altera `SSOT.md`; a adaptação permanece confinada a este documento.
- **Recursos nativos.** Usar apenas recursos do núcleo do PostgreSQL. Nenhuma extensão é obrigatória.
- **A restrição pertence ao banco quando o banco pode impô-la.** Enumerações, formatos, tamanhos e unicidade são restrições do banco, além da validação do contrato na aplicação.
- **Simplicidade.** Particionamento, índices especializados e otimizações só com necessidade medida.

# 4. Versão

A versão do PostgreSQL (major e minor) deve ser explicitamente fixada no ambiente de execução. Evitar tags flutuantes como `latest` ou apenas o major em integração, homologação e produção.

Uma atualização inclui: validação de compatibilidade dos clientes, execução das migrações e dos testes de contrato, revisão das notas de versão, teste de restauração e registro no changelog da plataforma. Atualizações de minor seguem a política de correções de segurança do ambiente.

Este documento não fixa uma versão. O DDL de referência foi exercitado em PostgreSQL 18.6 (ver a seção de verificação do DDL), e isso não é uma exigência de versão.

# 5. Organização

| Elemento | Regra |
|---|---|
| Banco | Um único banco para o SSOT de todos os módulos: `smarkee` |
| Proprietário | `smarkee`: dono do banco e dos objetos, usado somente por migração e recuperação; não é superusuário |
| Codificação e localidade | `UTF8`, com provedor de localidade `builtin` e `C.UTF-8` (PostgreSQL 17 ou superior): ordenação por ponto de código, igual em qualquer sistema operacional e biblioteca C, sem risco de índices invalidados por atualização da biblioteca |
| Schema | Um schema por módulo (`<módulo>`) |
| Tabelas | Quatro por tipo de recurso, todas com o mesmo formato: `<tipo>`, `<tipo>_operation`, `<tipo>_action_result`, `<tipo>_outbox` |
| Views | Duas por tipo de recurso, para a leitura da API: `<tipo>_v<MAJOR>` e `<tipo>_operation_v<MAJOR>` |
| Nomes | `snake_case`, minúsculas, sem hífen. Um tipo cujo nome é palavra reservada do PostgreSQL (por exemplo, `user`) mantém o nome do tipo, e a tabela do tipo é sempre citada (`core."user"`); as demais tabelas e views (`user_operation`, `user_v1`) não precisam de aspas |
| Papéis | Um por serviço, mapeando a identidade `<módulo>-<tipo>-<papel>` para `<módulo>_<tipo>_<papel>` |

As tabelas e as views de cada tipo são geradas **a partir de um único modelo** (`AGENTS.md`, arquivos gerados). A fonte é o modelo e o contrato do recurso; o objeto criado não é editado manualmente.

Motivo do banco único: o SSOT é um só sistema, com um só procedimento de backup, de recuperação e de migração. O isolamento entre módulos e tipos é feito por schema, por tabela e por `GRANT`, e não por banco. Bancos separados por módulo multiplicariam conexões, backups e procedimentos sem acrescentar isolamento que os privilégios já não garantam.

Motivo da tabela por tipo: o isolamento de acesso é feito por `GRANT` por tabela, sem exigir políticas por linha, e combina com a identidade por serviço. O custo é a quantidade de tabelas, que são idênticas e geradas.

O SSOT não compartilha banco com componentes de terceiros (por exemplo, gateway e provedor de identidade): cada um possui o seu banco e o seu proprietário. Fora do ambiente local, o SSOT usa um **cluster próprio**, porque o seu objetivo de recuperação, o seu procedimento de restauração (`SSOT.md`, recuperação) e o seu raio de impacto são diferentes dos de outros sistemas; restaurar o SSOT a um ponto no tempo não pode restaurar outro sistema junto.

# 6. Mapeamento do modelo lógico

## 6.1 Tabela `<tipo>` (Resource)

| Coluna | Tipo | Observação |
|---|---|---|
| `resource_id` | `text` | Chave primária; `CHECK` com o padrão de `SCHEMA.md` |
| `schema_version` | `text` | `MAJOR.MINOR` |
| `lifecycle` | `text` | `present` ou `absent` |
| `reconciliation` | `text` | `active` (padrão) ou `suspended` |
| `desired` | `jsonb` | Objeto; limite de tamanho |
| `desired_generation` | `bigint` | Maior ou igual a 1 |
| `resource_version` | `bigint` | Exposto como valor opaco (`MESSAGING.md`) |
| `observed` | `jsonb` | Nulo até a primeira observação |
| `presence` | `text` | `present`, `absent` ou `unknown` |
| `observed_at` | `timestamptz` | Nulo se, e somente se, `presence` for nulo |
| `phase` | `text` | `Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting` |
| `conditions` | `jsonb` | Array |
| `failure_count` | `integer` | Falhas da geração corrente |
| `created_at`, `updated_at` | `timestamptz` | |

`lifecycle`, `reconciliation`, `presence` e `phase` são colunas (não campos do `jsonb`) porque participam do controle, de restrições e de consulta. O `resource_version` é um contador interno; a interface o apresenta como texto opaco, sem semântica de ordenação.

## 6.2 Tabela `<tipo>_operation`

`operation_id` (chave primária, atribuída pela API conforme `SSOT.md`), `resource_id` (sem chave estrangeira: a Operation sobrevive à remoção física do recurso até a sua retenção), `operation_type`, `desired_generation` (nula somente em Operation rejeitada), `requested_by`, `correlation_id`, `request_digest`, `operation_status`, `operation_status_reason` (presente somente em Operation rejeitada), `created_at`, `updated_at`, `completed_at`.

A idempotência de `requested` é a chave primária `operation_id`. Não existe coluna nem índice para a chave de idempotência do cliente: ela é consumida pela API na derivação do `operation_id`, já escopada ao solicitante.

## 6.3 Tabela `<tipo>_action_result`

`action_id` (chave primária), `resource_id`, `desired_generation`, `action_outcome` (`completed` ou `failed`), `recorded_at` (com índice, para a retenção).

## 6.4 Tabela `<tipo>_outbox`

`sequence` (identidade, chave primária), `message_id` (único), `resource_id`, `subject`, `payload` (`jsonb`, com limite de tamanho), `created_at`, `published_at`. Dois índices parciais: pendentes (`sequence` onde `published_at` é nulo) e publicados (`published_at` onde não é nulo).

## 6.5 Views de leitura da API

A API não lê as tabelas. Ela lê as views `<tipo>_v<MAJOR>` e `<tipo>_operation_v<MAJOR>`, que são a **interface de leitura versionada** do SSOT (`SSOT.md`, leitura e consistência) e correspondem ao contrato da visão consolidada do recurso (`SCHEMA.md`, família de contratos). O `MAJOR` da view acompanha o `MAJOR` desse contrato.

- a view expõe apenas as colunas que a API pode ler; colunas internas de controle (`failure_count`) não aparecem. `request_digest` aparece porque a API o compara antes de publicar (`SSOT.md`, `requested`). Na view da Operation, `requested_by` aparece **somente para a API autorizar a leitura** (só o solicitante e os operadores leem uma Operation); a API não o devolve ao cliente. Na view do recurso, `requested_by` não existe;
- a view executa com os privilégios do proprietário (padrão do PostgreSQL), de modo que a API recebe `SELECT` somente na view, e nenhum privilégio nas tabelas;
- uma migração da tabela (expandir → migrar → contrair) não altera a view enquanto o contrato de leitura não mudar. Uma mudança incompatível do contrato cria a view do novo `MAJOR`, que coexiste com a anterior durante a janela de coexistência.

## 6.6 DDL de referência

O DDL abaixo é o **modelo de referência para um tipo** (`sample.item`). Não é normativo: o contrato do recurso e o modelo gerado prevalecem, e o DDL deve ser validado no ambiente.

```sql
CREATE SCHEMA sample;

CREATE TABLE sample.item (
  resource_id        text        PRIMARY KEY
                     CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  schema_version     text        NOT NULL CHECK (schema_version ~ '^[0-9]+\.[0-9]+$'),
  lifecycle          text        NOT NULL CHECK (lifecycle IN ('present', 'absent')),
  reconciliation     text        NOT NULL DEFAULT 'active' CHECK (reconciliation IN ('active', 'suspended')),
  desired            jsonb       NOT NULL
                     CHECK (jsonb_typeof(desired) = 'object' AND pg_column_size(desired) <= 262144),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  resource_version   bigint      NOT NULL DEFAULT 1,
  observed           jsonb
                     CHECK (observed IS NULL OR (jsonb_typeof(observed) = 'object' AND pg_column_size(observed) <= 262144)),
  presence           text        CHECK (presence IN ('present', 'absent', 'unknown')),
  observed_at        timestamptz,
  phase              text        NOT NULL CHECK (phase IN ('Pending', 'Reconciling', 'Ready', 'Failed', 'Deleting')),
  conditions         jsonb       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(conditions) = 'array'),
  failure_count      integer     NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK ((presence IS NULL) = (observed_at IS NULL))
);

CREATE TABLE sample.item_operation (
  operation_id            text        PRIMARY KEY CHECK (length(operation_id) BETWEEN 1 AND 128),
  resource_id             text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  operation_type          text        NOT NULL CHECK (operation_type IN ('create', 'update', 'delete')),
  desired_generation      bigint      CHECK (desired_generation >= 1),
  requested_by            text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  correlation_id          text        NOT NULL CHECK (length(correlation_id) BETWEEN 1 AND 256),
  request_digest          text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  operation_status        text        NOT NULL
                          CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected')),
  operation_status_reason text        CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found')),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  completed_at            timestamptz,
  CHECK ((operation_status = 'rejected') = (operation_status_reason IS NOT NULL)),
  CHECK ((operation_status = 'rejected') = (desired_generation IS NULL))
);
CREATE INDEX item_operation_resource ON sample.item_operation (resource_id, created_at);
CREATE INDEX item_operation_retention ON sample.item_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE sample.item_action_result (
  action_id          text        PRIMARY KEY CHECK (length(action_id) BETWEEN 1 AND 512),
  resource_id        text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  action_outcome     text        NOT NULL CHECK (action_outcome IN ('completed', 'failed')),
  recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX item_action_result_recorded ON sample.item_action_result (recorded_at);

CREATE TABLE sample.item_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX item_outbox_pending   ON sample.item_outbox (sequence)     WHERE published_at IS NULL;
CREATE INDEX item_outbox_published ON sample.item_outbox (published_at) WHERE published_at IS NOT NULL;

CREATE VIEW sample.item_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM sample.item;

CREATE VIEW sample.item_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at
    FROM sample.item_operation;
```

O limite de 262144 bytes (256 KiB) é o valor de referência de `SCHEMA.md` e pode ser ajustado por contrato. `pg_column_size` mede o valor armazenado, que pode estar comprimido; o limite da aplicação continua sendo a verificação autoritativa do tamanho do conteúdo. Os limites de comprimento das colunas de identificação seguem os valores de referência de `SCHEMA.md`; o de `action_id` comporta a sua composição (`MESSAGING.md`).

`request_digest` é o SHA-256, em hexadecimal minúsculo, calculado pela API (`SSOT.md`, Operation). Ele não é calculado a partir do texto do `jsonb` (ver propriedades do `jsonb`).

# 7. JSONB

## 7.1 O que é `jsonb` e o que é coluna

| `jsonb` | Coluna |
|---|---|
| `desired` (conteúdo declarativo do contrato) | Identidade, `lifecycle`, `reconciliation`, `phase`, `presence` |
| `observed` | Gerações, `resource_version`, `failure_count` |
| `conditions` | Tempos e `schema_version` |
| `payload` do outbox | Tudo o que é usado em restrição, concorrência ou consulta frequente |

`jsonb` não substitui modelagem: não se usa `jsonb` para evitar uma coluna que participa de identidade, unicidade, concorrência ou consulta do loop.

## 7.2 Propriedades do `jsonb` que importam aqui

Conforme a documentação oficial do PostgreSQL:

- `jsonb` **não preserva a ordem das chaves nem os espaços**, mantém **apenas a última chave duplicada** e **normaliza números**. O conteúdo gravado não é o texto original. Isso favorece a comparação semântica (duas representações da mesma estrutura são iguais), e impede tratar o valor como texto bruto, por exemplo para assinatura ou hash do texto;
- `jsonb` rejeita `\u0000`, `NaN` e infinito, e números fora do intervalo de `numeric`. O contrato do recurso deve evitá-los;
- o banco deve usar codificação UTF-8 (ver a localidade na seção de organização);
- **toda atualização bloqueia a linha inteira**. Documentos grandes aumentam a contenção. Por isso o conteúdo é limitado em tamanho e cada recurso é um registro pequeno.

## 7.3 Comparação e geração

A igualdade de `jsonb` é semântica (independe de ordem de chaves). Ela é usada para decidir se a **especificação** mudou:

```sql
desired_generation = desired_generation
  + (CASE WHEN desired IS DISTINCT FROM $novo_desired THEN 1 ELSE 0 END)
```

Por causa da normalização numérica, `1.0` e `1.00` são iguais; valores que o contrato trate como diferentes não devem depender dessa diferença.

A comparação entre `desired` e `observed` do control loop (campos gerenciados e normalização) é feita pelo Reconciler com as anotações do contrato (`SCHEMA.md`), e não pelo banco.

## 7.4 Índices

Nenhum índice GIN é criado por padrão. O loop acessa os registros por `resource_id`. Um índice GIN (`jsonb_path_ops` para contenção, `jsonb_ops` quando for preciso consultar existência de chave) só é adicionado com consulta medida e justificada, pois aumenta o custo de escrita e o tamanho.

# 8. Transações e isolamento

- O nível de isolamento é **Read Committed** (padrão). Nível mais alto (Repeatable Read ou Serializable) faria transações falharem com erro de serialização e não é necessário, porque a serialização por recurso é obtida pelo bloqueio da linha.
- Cada mensagem consumida pelo Manager é **uma transação**, e a confirmação ao transporte ocorre depois do `COMMIT`.
- **Toda transação sobre um recurso existente começa bloqueando a sua linha** e só então lê o estado:

```sql
SELECT resource_version, desired_generation, desired, reconciliation, observed_at,
       phase, conditions, failure_count
  FROM sample.item
 WHERE resource_id = $id
   FOR UPDATE;
```

  Em Read Committed, cada comando enxerga o que foi confirmado antes do seu início. Como a segunda transação sobre o mesmo recurso espera o `COMMIT` da primeira no `FOR UPDATE`, as leituras seguintes já enxergam o resultado da primeira. Isso implementa a invariante 9 de `SSOT.md`: `observed`, `completed` e `failed` do mesmo recurso, processados em paralelo por instâncias diferentes, nunca calculam `conditions` e `phase` sobre o mesmo estado lido.
- Nenhuma linha retornada pelo `FOR UPDATE` significa recurso inexistente.
- Na criação ainda não há linha para bloquear. Duas entregas simultâneas do mesmo `requested` disputam a chave primária de `<tipo>_operation` e de `<tipo>`: a segunda espera a primeira e recebe violação de unicidade (`23505`), que é tratada como reentrega (desfazer a transação e confirmar a mensagem).
- Cada transação bloqueia **uma única linha de recurso**; por isso não há ciclo de espera entre transações do Manager. A aplicação repete a transação a partir do estado atual em falha transitória: perda de conexão, `lock_timeout` (`55P03`), deadlock (`40P01`) ou falha de serialização (`40001`), com limite de tentativas e atraso crescente. Esgotadas as tentativas, a mensagem não é confirmada e segue a política de retry do transporte.
- Transações são curtas e não incluem chamadas externas.
- A **linha do recurso é bloqueada e atualizada antes da inserção no outbox**, na mesma transação. Isso é essencial para a ordem do outbox (ver a seção do relay).

# 9. Concorrência otimista

A concorrência otimista protege o **solicitante** (`SSOT.md`, concorrência). Com a linha já bloqueada, a atualização confere a `resource_version` informada no pedido:

```sql
UPDATE sample.item
   SET desired            = $desired,
       desired_generation = desired_generation
                          + (CASE WHEN desired IS DISTINCT FROM $desired THEN 1 ELSE 0 END),
       failure_count      = CASE WHEN desired IS DISTINCT FROM $desired THEN 0 ELSE failure_count END,
       resource_version   = resource_version + 1,
       updated_at         = now()
 WHERE resource_id = $id
   AND resource_version = $versao_informada
RETURNING desired_generation, resource_version;
```

- Como a linha está bloqueada e a sua existência já foi conferida, zero linhas afetadas significa **conflito** (versão desatualizada). A Operation é gravada como `rejected` com motivo `conflict`, e nenhum `desired` é registrado.
- A mudança apenas de `reconciliation` usa o mesmo comando sem alterar `desired`: a geração não incrementa, e `resource_version` sim.
- As expressões de `SET` usam os valores **anteriores** da linha, o que torna a decisão sobre a geração atômica.
- As atualizações internas (`observed`, `completed`, `failed`) não informam `resource_version`: elas já estão serializadas pelo bloqueio da linha e incrementam `resource_version` ao gravar.

# 10. Idempotência de entrada

## 10.1 `requested`

A Operation é a chave de idempotência (`SSOT.md`). Depois do bloqueio da linha (quando existir):

```sql
SELECT request_digest FROM sample.item_operation WHERE operation_id = $operation_id;
```

Uma linha retornada significa reentrega ou repetição do cliente: a transação é desfeita e a mensagem é confirmada. Um `request_digest` diferente do recebido é registrado como sinal de observabilidade, sem alterar a Operation. A Operation é gravada uma única vez, como `accepted` ou como `rejected`:

```sql
INSERT INTO sample.item_operation
       (operation_id, resource_id, operation_type, desired_generation, requested_by,
        correlation_id, request_digest, operation_status, operation_status_reason)
VALUES ($operation_id, $id, $operation_type, $desired_generation, $requested_by,
        $correlation_id, $request_digest, $operation_status, $operation_status_reason);
```

## 10.2 `observed`

Monotonia de `observed_at`, com a linha já bloqueada:

```sql
UPDATE sample.item
   SET observed = $observed, presence = $presence, observed_at = $observed_at,
       conditions = $conditions, phase = $phase,
       resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = $id
   AND (observed_at IS NULL OR observed_at < $observed_at)
RETURNING resource_version;
```

Zero linhas afetadas significa observação não mais recente: a mensagem é descartada como já refletida. `conditions` e `phase` são calculados pela aplicação a partir do estado lido sob bloqueio.

## 10.3 `completed` e `failed`

O `actionId` é registrado em `<tipo>_action_result` antes de qualquer efeito:

```sql
INSERT INTO sample.item_action_result (action_id, resource_id, desired_generation, action_outcome)
VALUES ($action_id, $id, $desired_generation, $action_outcome)
ON CONFLICT (action_id) DO NOTHING
RETURNING action_id;
```

Nenhuma linha retornada significa **resultado já contabilizado**: a transação é desfeita e a mensagem é confirmada. O `RETURNING` exige o privilégio `SELECT` na coluna.

Um resultado cuja `desired_generation` é diferente da geração atual (lida sob bloqueio) atualiza a Operation, mas não altera `failure_count` nem `phase` (`SSOT.md`). Ao atingir o `failureLimit`, a mesma transação grava `phase = 'Failed'` e `reconciliation = 'suspended'` na linha e registra no outbox o `desired` correspondente.

# 11. Outbox e relay

## 11.1 Gravação

A mensagem é inserida no outbox **na mesma transação** da alteração que a originou, depois do bloqueio e do `UPDATE` do recurso:

```sql
INSERT INTO sample.item_outbox (message_id, resource_id, subject, payload)
VALUES ($message_id, $id, $subject, $payload);
```

## 11.2 Ordem por recurso

O `sequence` é atribuído no momento da inserção. Como a transação bloqueia primeiro a linha do recurso, **duas transações sobre o mesmo recurso são serializadas pelo bloqueio da linha**: a segunda só insere no outbox depois que a primeira confirmou. Logo, para um mesmo recurso, a ordem de `sequence` é a ordem de confirmação.

Entre recursos diferentes não há garantia de ordem, e ela não é necessária.

## 11.3 Leitura pelo relay

O relay lê por consulta periódica, **sem marca-d'água por sequência** e sem bloqueio de linha:

```sql
SELECT sequence, message_id, subject, payload
  FROM sample.item_outbox
 WHERE published_at IS NULL
 ORDER BY sequence
 LIMIT $lote;
```

Motivo da ausência de marca-d'água: uma transação pode confirmar depois de outra de `sequence` maior (recursos diferentes), de modo que uma mensagem de `sequence` menor pode aparecer depois. Selecionar sempre por `published_at IS NULL` garante que ela seja encontrada na rodada seguinte; guardar apenas "o último sequence publicado" a perderia.

Motivo da ausência de `FOR UPDATE`: a exclusão mútua entre instâncias é dada pela trava consultiva (seção seguinte), e o Manager só insere linhas novas. Bloquear as linhas durante a publicação manteria bloqueios abertos durante I/O de rede sem acrescentar garantia.

## 11.4 Uma instância ativa

Para preservar a ordem por recurso, **uma única instância do relay publica por vez**, por tabela de outbox, usando trava consultiva de sessão:

```sql
SELECT pg_try_advisory_lock(hashtext('sample.item_outbox'));
```

- A instância que não obtém a trava aguarda e tenta de novo. A trava é liberada quando a sessão termina, o que habilita o failover.
- A trava é **de sessão**: exige conexão direta ou *pooling* de sessão. *Pooling* em modo de transação invalida a garantia e deve ser evitado no relay (validar no ambiente). O papel do relay não usa `idle_session_timeout`, que encerraria a sessão que detém a trava.
- Uma colisão de `hashtext` entre duas tabelas faz as duas compartilharem a mesma trava. Isso reduz a vazão, mas não compromete a ordem.
- **Exclusividade durante o lote.** O banco pode encerrar a sessão (falha de rede, failover, encerramento administrativo) enquanto a instância ainda publica um lote lido antes. Para limitar a sobreposição com a nova instância: antes de cada lote a instância confirma que ainda detém a trava; qualquer erro de conexão descarta o lote em memória e interrompe a publicação; e a duração de um lote é limitada a uma fração da janela de deduplicação do transporte. Assim, uma mensagem repetida pela sobreposição é descartada pela deduplicação do transporte (`Nats-Msg-Id`).

```sql
SELECT EXISTS (
  SELECT 1 FROM pg_locks
   WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted
     AND objid = hashtext('sample.item_outbox')::oid
);
```

**`FOR UPDATE SKIP LOCKED` não é usado.** Em uma sobreposição de duas instâncias, `SKIP LOCKED` faz a segunda pular o lote da primeira e publicar linhas posteriores antes das anteriores. A documentação do PostgreSQL também classifica `SKIP LOCKED` como visão inconsistente, adequada a filas em que a ordem não importa. Se a vazão exigir mais de uma instância, a alternativa é particionar o relay por hash de `resource_id`, com uma trava por partição, preservando a ordem por recurso.

## 11.5 Publicação e marcação

A publicação é **sequencial** (`SSOT.md`, outbox):

1. publicar a mensagem no transporte, com a sua identidade (`message_id`) como chave de deduplicação do transporte;
2. aguardar a confirmação do transporte antes de publicar a próxima;
3. em erro, interromper o lote: as mensagens seguintes não são publicadas nesta rodada;
4. marcar `published_at` das mensagens confirmadas.

```sql
UPDATE sample.item_outbox SET published_at = now() WHERE sequence = ANY($sequences);
```

Publicar em paralelo e tratar os erros depois permitiria que uma mensagem antiga, repetida após um erro, fosse gravada depois de uma nova do mesmo recurso. Em um stream que retém apenas a última mensagem por endereço, a geração antiga passaria a ser o estado retido.

Uma falha entre a confirmação do transporte e a marcação provoca republicação (entrega *pelo menos uma vez*). A deduplicação do transporte e a idempotência dos consumidores a absorvem.

Uma mensagem **não** é marcada como publicada sem a confirmação do transporte. Em falha de publicação, ela permanece pendente, e o relay insiste com atraso crescente, sem pular a mensagem.

## 11.6 Atraso

O atraso do relay é observável: idade da mensagem pendente mais antiga (`now() - min(created_at)` onde `published_at` é nulo) e quantidade pendente.

# 12. Retenção

| Tabela | Regra |
|---|---|
| Outbox | Remover mensagens publicadas após o prazo de retenção (`DELETE` em lote por `published_at`) |
| ActionResult | Remover registros com `recorded_at` mais antigo que a retenção dos resultados no transporte somada ao prazo máximo de reentrega (`DELETE` em lote) |
| Operation | Remover operações encerradas (`completed`, `failed`, `rejected`) após o prazo de retenção, que é maior que o prazo máximo de reentrega do `requested`; o que deve durar mais pertence à auditoria |

A remoção é feita por uma **identidade de manutenção** própria, com `DELETE` apenas nessas tabelas. Os serviços de runtime não removem outbox, resultados nem operações.

O particionamento por tempo é uma evolução possível, adotada apenas com volume medido: remover uma partição é muito mais barato que `DELETE` em massa. A restrição é que chaves únicas e primárias de uma tabela particionada devem incluir a chave de partição. Por isso só o **outbox** é candidato: `<tipo>_operation` e `<tipo>_action_result` dependem da unicidade global das suas chaves primárias para a idempotência e não são particionadas por tempo.

# 13. Remoção de recursos

A remoção segue `SSOT.md`:

1. o pedido de remoção atualiza o recurso para `lifecycle = absent`, `phase = Deleting` e registra o outbox (`desired`);
2. após a convergência (`presence = absent`), o Manager remove o registro com `DELETE` em uma transação que também registra o outbox (`updated`);
3. a Operation permanece até a sua retenção, e por isso não há chave estrangeira entre `<tipo>_operation` e `<tipo>`.

# 14. Segurança

## 14.1 Banco

O banco `smarkee` é criado pela infraestrutura, com o proprietário `smarkee`. O PostgreSQL concede por padrão `CONNECT` e `TEMPORARY` em todo banco a `PUBLIC`, e `USAGE` no schema `public`; esses privilégios são removidos:

```sql
REVOKE ALL ON DATABASE smarkee FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
```

Cada papel de serviço recebe `CONNECT` explicitamente, junto dos seus privilégios no módulo.

## 14.2 Papéis

Um papel por serviço, sem login nos papéis de função: o login é concedido pela infraestrutura, com credencial própria.

| Papel | Privilégios |
|---|---|
| `<módulo>_<tipo>_manager` | `SELECT`, `INSERT`, `UPDATE` e `DELETE` em `<tipo>`; `SELECT`, `INSERT` e `UPDATE` em `<tipo>_operation`; `SELECT` e `INSERT` em `<tipo>_action_result`; `INSERT` em `<tipo>_outbox` |
| `<módulo>_<tipo>_api` | `SELECT` em `<tipo>_v<MAJOR>` e `<tipo>_operation_v<MAJOR>`; nenhum privilégio nas tabelas |
| `<módulo>_relay` | `SELECT` em `<tipo>_outbox` e `UPDATE (published_at)` |
| `<módulo>_maintenance` | `SELECT` e `DELETE` em `<tipo>_outbox`, `<tipo>_action_result` e `<tipo>_operation` |
| `smarkee` (administração) | Dono do banco e dos objetos; migração e procedimento de recuperação (`SSOT.md`); não é usado por serviços de runtime |

```sql
GRANT CONNECT ON DATABASE smarkee TO sample_item_manager, sample_item_api, sample_relay, sample_maintenance;

REVOKE ALL ON SCHEMA sample FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA sample FROM PUBLIC;
GRANT USAGE ON SCHEMA sample TO sample_item_manager, sample_item_api, sample_relay, sample_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON sample.item               TO sample_item_manager;
GRANT SELECT, INSERT, UPDATE         ON sample.item_operation     TO sample_item_manager;
GRANT SELECT, INSERT                 ON sample.item_action_result TO sample_item_manager;
GRANT INSERT                         ON sample.item_outbox        TO sample_item_manager;

GRANT SELECT ON sample.item_v1, sample.item_operation_v1 TO sample_item_api;

GRANT SELECT ON sample.item_outbox TO sample_relay;
GRANT UPDATE (published_at) ON sample.item_outbox TO sample_relay;

GRANT SELECT, DELETE ON sample.item_outbox, sample.item_action_result, sample.item_operation TO sample_maintenance;
```

Pontos relevantes:

- o PostgreSQL não concede privilégios padrão em tabelas e em schemas criados, mas o `REVOKE` explícito de `PUBLIC` é mantido como defesa contra mudanças de padrão e de herança;
- as views são simples e, portanto, atualizáveis pelo PostgreSQL; a API não as altera porque possui somente `SELECT`;
- o Manager **não** possui `DELETE` em outbox, resultados e operation, nem `SELECT` e `UPDATE` no outbox, nem privilégio de alterar a estrutura;
- a API não lê `failure_count`, `requested_by` nem nenhuma tabela de controle de mensagens.

Em cada alteração do modelo, a matriz de privilégios é revisada contra a matriz de identidades de `RESOURCE-CONTROL-SECURITY.md`.

## 14.3 Parâmetros de sessão por papel

Os papéis de runtime limitam o tempo que uma sessão pode segurar recursos, e fixam o caminho de busca para que nenhum nome seja resolvido em um schema inesperado. Os valores são parâmetros do ambiente; os abaixo são de referência.

Os parâmetros são definidos no **papel de login** de cada serviço, criado pela infraestrutura como membro do papel de função. O PostgreSQL aplica apenas os parâmetros do papel que inicia a sessão: definidos no papel de função (sem login), eles **não** se aplicam ao papel de login que o herda (verificado).

```sql
-- <login> é o papel de login concedido pela infraestrutura ao serviço (membro de sample_item_manager).
ALTER ROLE <login> SET search_path = '';
ALTER ROLE <login> SET lock_timeout = '2s';
ALTER ROLE <login> SET statement_timeout = '5s';
ALTER ROLE <login> SET idle_in_transaction_session_timeout = '10s';
```

- `search_path = ''` exige nomes qualificados pelo schema (`sample.item`), que é a forma usada por todo o SQL deste documento;
- `idle_in_transaction_session_timeout` impede que uma instância travada mantenha o bloqueio da linha de um recurso indefinidamente;
- os mesmos parâmetros se aplicam à API, ao relay e à manutenção, exceto `idle_session_timeout` no relay (ver a seção do relay);
- o limite de conexões por papel (`CONNECTION LIMIT`) é definido pela infraestrutura conforme o dimensionamento.

## 14.4 Isolamento por tipo

O isolamento entre tipos de recurso é obtido por privilégios por tabela e por view. **Row-Level Security não é adotada**: a combinação de uma tabela por tipo e privilégios por objeto cumpre o isolamento com menos mecanismos. Se um tipo precisar de isolamento por linha (por exemplo, por organization), ele é tratado explicitamente no contrato e a RLS é reavaliada; nesse caso, as views passam a usar `security_invoker`, para que a política se aplique ao papel da API.

## 14.5 Conexão, repouso e segredos

- conexões usam TLS fora do ambiente local, com validação do certificado do servidor, e preferencialmente autenticação mútua para serviços;
- este documento **não assume** criptografia nativa do banco em repouso: a proteção em repouso é exigida da plataforma (volume ou equivalente) e deve ser validada no ambiente, conforme a classificação dos dados;
- credenciais são fornecidas por gestão de segredos, nunca versionadas;
- parâmetros de comandos e valores de colunas `confidential` não são registrados em log (configuração de log do servidor e do cliente);
- mensagens de erro do banco não são devolvidas ao cliente externo.

# 15. Migrações

- migrações são **versionadas, revisadas e executadas por infraestrutura** com o proprietário dos objetos. Serviços de runtime não executam DDL;
- a estrutura de cada tipo é gerada do modelo; uma mudança no modelo é aplicada a todos os tipos pelo mesmo mecanismo;
- a evolução segue **expandir → migrar → contrair**: adicionar de forma compatível, migrar o conteúdo e só então remover o antigo. É a tradução, para o banco, da sequência de `SCHEMA.md`;
- as views de leitura isolam a API das migrações da tabela; uma view só muda quando o contrato de leitura muda, e uma mudança incompatível cria a view do novo `MAJOR`;
- uma mudança `MAJOR` de contrato exige conversão na leitura durante a coexistência e migração do conteúdo gravado e da mensagem retida, com republicação preservando geração e conteúdo;
- `schema_version` de cada registro indica o que ainda não foi migrado;
- DDL que bloqueia a tabela por muito tempo (reescrita completa) deve ser avaliado antes, e executado em janela ou por técnica de baixo bloqueio, a validar no ambiente.

# 16. Backup e recuperação

- cópia de segurança com **recuperação a um ponto no tempo (PITR)**: backup base mais arquivamento contínuo de WAL, armazenados fora do servidor do banco;
- a **replicação não é cópia de segurança**: um erro lógico é replicado imediatamente para os standbys;
- a restauração é **testada periodicamente**, incluindo o procedimento de recuperação, e o resultado é registrado;
- os objetivos de recuperação (ponto e tempo) são parâmetros do ambiente;
- versões recentes do PostgreSQL suportam backups incrementais; o seu uso é uma decisão do ambiente.

## 16.1 Procedimento de recuperação

Após uma restauração a um ponto anterior, o procedimento de `SSOT.md` (recuperação após restauração) é executado com `smarkee`, com o Manager e o relay parados (papéis sem login ou serviços desligados):

1. descartar as mensagens pendentes: `DELETE FROM <módulo>.<tipo>_outbox WHERE published_at IS NULL`;
2. para cada recurso, ler a geração e o conteúdo do último `desired` retido no transporte (leitura direta do último valor do subject, `NATS.md`) e compará-los com `desired_generation` e `desired`;
3. quando o procedimento exigir nova geração, gravar `desired_generation = <geração do transporte> + 1`, incrementar `resource_version` e inserir o `desired` correspondente no outbox, na mesma transação;
4. listar os recursos presentes no transporte e ausentes na tabela, sem alterá-los;
5. registrar o relatório e só então liberar o Manager e o relay.

A comparação de conteúdo usa a igualdade de `jsonb` (seção de comparação e geração), com o conteúdo do transporte convertido para `jsonb`.

# 17. Alta disponibilidade

- o banco usa replicação com failover definidos pela infraestrutura;
- o failover interrompe transações em andamento: a unidade atômica é repetida a partir do estado atual, e a mensagem só é confirmada ao transporte após o `COMMIT`;
- a replicação usada para failover é síncrona ou o failover é tratado como restauração: um failover assíncrono pode perder transações confirmadas cujas mensagens já foram publicadas, o que equivale a voltar a um ponto anterior (`SSOT.md`, recuperação);
- o relay reabre a trava consultiva na nova instância e republica o que estiver pendente;
- com o banco indisponível, o Manager não aceita novos pedidos nem atualiza o estado, e o loop continua sobre o `desired` já publicado (`SSOT.md`). Isso deve gerar alerta;
- a leitura em réplica pela API aceita atraso de replicação; leituras que precisam refletir a própria escrita (por exemplo, a resposta de uma criação) devem usar o primário.

# 18. Observabilidade

Medir, sem expor dados sensíveis:

```text
idade da mensagem pendente mais antiga no outbox
quantidade pendente no outbox
tamanho de outbox, action_result e operation
Operations rejected por motivo e reusos de chave com outro resumo
transações repetidas por conexão, lock_timeout, deadlock ou serialização
esperas por bloqueio de linha e duração das transações do Manager
posse da trava consultiva do relay e lotes interrompidos
tamanho das tabelas e dos índices
atraso de replicação
atraso do arquivamento de WAL
idade do último backup base e do último teste de restauração
quantidade de recursos por phase, em Failed e com reconciliação suspensa
```

# 19. Anti-padrões

- escrever no banco por serviço que não seja o Manager;
- ler o estado do recurso sem `FOR UPDATE` antes de gravar;
- registrar o outbox sem bloquear e atualizar antes a linha do recurso na mesma transação (quebra a ordem por recurso);
- contar um resultado sem registrar antes o seu `action_id`;
- índice de idempotência apenas pela chave do cliente, sem o escopo do solicitante;
- usar marca-d'água de sequência para publicar o outbox;
- usar `FOR UPDATE SKIP LOCKED` no relay ordenado;
- publicar o outbox em paralelo, ou por mais de uma instância sem partição determinística por recurso;
- relay em *pooling* de transação com trava consultiva de sessão;
- confirmar a mensagem ao transporte antes do `COMMIT`;
- API lendo tabelas em vez das views de leitura;
- índice GIN por padrão;
- usar `jsonb` para o que participa de concorrência, unicidade ou consulta do loop;
- tratar o texto de um `jsonb` como original (assinatura, hash);
- documentos grandes em um único registro;
- conceder `DELETE` em outbox, resultados ou operation ao Manager;
- executar DDL por serviço de runtime;
- deixar `CONNECT` e `TEMPORARY` do banco para `PUBLIC`;
- liberar o Manager e o relay após uma restauração sem o procedimento de recuperação;
- confiar na replicação como cópia de segurança.

# 20. Checklist

- [ ] A versão do PostgreSQL está fixada no ambiente?
- [ ] O banco `smarkee` pertence a `smarkee`, sem privilégios para `PUBLIC`?
- [ ] As quatro tabelas e as duas views do tipo são geradas do modelo?
- [ ] `lifecycle`, `reconciliation`, `presence`, `phase` e `operation_status` possuem `CHECK`?
- [ ] `resource_id`, identificadores, tamanho e tipo dos `jsonb` possuem `CHECK`?
- [ ] Toda transação sobre um recurso existente começa com `FOR UPDATE` na linha?
- [ ] A atualização do solicitante usa `resource_version` na condição e registra o conflito na Operation?
- [ ] A geração só incrementa quando a especificação muda?
- [ ] `requested` é deduplicado por `operation_id`, e resultados por `action_id`, com filtro de geração?
- [ ] O relay usa uma instância ativa por trava consultiva, publica sequencialmente, sem marca-d'água e sem `SKIP LOCKED`?
- [ ] O relay só marca `published_at` após a confirmação do transporte?
- [ ] A matriz de privilégios corresponde à matriz de identidades de `RESOURCE-CONTROL-SECURITY.md`?
- [ ] A API lê somente as views?
- [ ] O Manager não possui `DELETE` em outbox, resultados e operation?
- [ ] Os papéis de login de runtime têm `search_path`, `lock_timeout`, `statement_timeout` e `idle_in_transaction_session_timeout`?
- [ ] Existe identidade de manutenção para a retenção?
- [ ] TLS está habilitado fora do ambiente local, e a proteção em repouso foi validada?
- [ ] Parâmetros e colunas `confidential` não aparecem em log?
- [ ] Existe PITR, teste periódico de restauração e procedimento de recuperação?
- [ ] As migrações seguem expandir → migrar → contrair, por infraestrutura?

# 21. Verificação do DDL de referência

O DDL, os `GRANT` e os comportamentos descritos neste documento foram exercitados no banco `smarkee` do ambiente de desenvolvimento (`infrastructure/dev/database`, **PostgreSQL 18.6**), com papéis e dados de teste removidos ao final:

- criação do banco e do proprietário pela inicialização do ambiente, reaplicação idempotente, `PUBLIC` sem `CONNECT` no banco e sem privilégio no schema `public`, e autenticação por senha (SCRAM) pela rede interna;
- parâmetros de sessão: aplicados ao papel de login, não herdados do papel de função; `search_path` vazio exige nome qualificado; `lock_timeout` encerra a espera por bloqueio (`55P03`);

- restrições (`CHECK`) de `resource_id`, de enumerações, de tipo `jsonb`, da coerência entre `presence` e `observed_at`, e da coerência entre `operation_status`, `operation_status_reason` e `desired_generation`;
- concorrência otimista (versão antiga não altera linhas), geração não incrementa com a mesma especificação (inclusive com ordem de chaves diferente) nem ao mudar só `reconciliation`, e incrementa e zera `failure_count` quando a especificação muda;
- monotonia de `observed_at`;
- serialização por `FOR UPDATE`: duas sessões sobre o mesmo recurso, a segunda enxergando o resultado da primeira após o bloqueio;
- deduplicação de resultado com `ON CONFLICT DO NOTHING ... RETURNING` em `action_result`;
- deduplicação de `requested` por violação de chave primária de `operation_id` entre duas sessões simultâneas;
- privilégios: leitura da API somente pelas views (negação nas tabelas), negação de `PUBLIC` no banco, negação de `DELETE` e de DDL ao Manager, Manager sem `SELECT` no outbox, `UPDATE (published_at)` do relay e `DELETE` da manutenção;
- ordem do outbox por recurso entre duas sessões concorrentes, visibilidade fora de ordem entre recursos diferentes, exclusão mútua da trava consultiva e a consulta de posse da trava.

**Não foi verificado:** carga e desempenho, relay real com transporte, publicação sequencial com erro de transporte, failover, PITR e o procedimento de recuperação com transporte real, criptografia em repouso, *pooling* de conexões e o custo de DDL em tabelas grandes. Esses pontos devem ser validados no ambiente.

# 22. Fontes técnicas

A implementação deste documento utiliza como referência a documentação oficial do PostgreSQL:

- Tipos JSON: https://www.postgresql.org/docs/current/datatype-json.html
- Isolamento de transações: https://www.postgresql.org/docs/current/transaction-iso.html
- Bloqueio explícito e travas consultivas: https://www.postgresql.org/docs/current/explicit-locking.html
- INSERT e `ON CONFLICT`: https://www.postgresql.org/docs/current/sql-insert.html
- SELECT e cláusulas de bloqueio: https://www.postgresql.org/docs/current/sql-select.html
- Views: https://www.postgresql.org/docs/current/sql-createview.html
- Privilégios: https://www.postgresql.org/docs/current/ddl-priv.html
- Parâmetros de sessão do cliente: https://www.postgresql.org/docs/current/runtime-config-client.html
- Restrições: https://www.postgresql.org/docs/current/ddl-constraints.html
- Particionamento: https://www.postgresql.org/docs/current/ddl-partitioning.html
- Arquivamento contínuo e PITR: https://www.postgresql.org/docs/current/continuous-archiving.html

# 23. Fonte de verdade

`SSOT.md` é a fonte de verdade do modelo e das garantias de gravação.

`POSTGRESQL.md` é a fonte de verdade da implementação dessas garantias em PostgreSQL.

```text
SSOT.md
    |
    v
POSTGRESQL.md
```

Uma limitação específica do PostgreSQL não altera o modelo. Quando a implementação exigir adaptação, a adaptação permanece confinada a este documento e à infraestrutura.
