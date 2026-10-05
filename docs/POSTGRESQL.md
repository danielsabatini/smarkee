# PostgreSQL

# 1. Introdução

Este documento define a implementação de referência do SSOT em PostgreSQL, com `jsonb` para o conteúdo declarativo. O modelo, as invariantes e as garantias são definidos exclusivamente em `SSOT.md`.

PostgreSQL é uma tecnologia de armazenamento. Este documento descreve como o modelo lógico é materializado em schemas, tabelas, colunas, restrições, privilégios e rotinas de manutenção.

```text
SSOT.md
    |
    v
POSTGRESQL.md
```

# 2. Objetivos

Estabelecer uma implementação PostgreSQL consistente, previsível, segura e resiliente das garantias de `SSOT.md`: unidade atômica de gravação por mensagem, concorrência otimista, idempotência semântica, outbox ordenado por recurso, privilégios mínimos, migração segura e recuperação a um ponto no tempo.

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
| Banco | Um banco para o SSOT |
| Schema | Um schema por módulo (`<módulo>`) |
| Tabelas | Quatro por tipo de recurso, todas com o mesmo formato: `<tipo>`, `<tipo>_operation`, `<tipo>_outbox`, `<tipo>_inbox` |
| Nomes | `snake_case`, minúsculas, sem hífen |
| Papéis | Um por serviço, mapeando a identidade `<módulo>-<tipo>-<papel>` para `<módulo>_<tipo>_<papel>` |

As quatro tabelas de cada tipo são geradas **a partir de um único modelo** (`AGENTS.md`, arquivos gerados). A fonte é o modelo e o contrato do recurso; a tabela criada não é editada manualmente.

Motivo da tabela por tipo: o isolamento de acesso é feito por `GRANT` por tabela, sem exigir políticas por linha, e combina com a identidade por serviço. O custo é a quantidade de tabelas, que são idênticas e geradas.

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

`operation_id` (chave), `resource_id` (sem chave estrangeira: a Operation sobrevive à remoção física do recurso até a sua retenção), `operation_type`, `desired_generation`, `requested_by`, `correlation_id`, `idempotency_key`, `status`, `created_at`, `updated_at`, `completed_at`. Índice único parcial em `idempotency_key` (quando não nulo).

## 6.3 Tabela `<tipo>_outbox`

`sequence` (identidade, chave primária), `message_id` (único), `resource_id`, `subject`, `payload` (`jsonb`, com limite de tamanho), `created_at`, `published_at`. Dois índices parciais: pendentes (`sequence` onde `published_at` é nulo) e publicados (`published_at` onde não é nulo).

## 6.4 Tabela `<tipo>_inbox`

`message_id` (chave primária), `received_at` (com índice).

## 6.5 DDL de referência

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
  operation_id       text        PRIMARY KEY,
  resource_id        text        NOT NULL,
  operation_type     text        NOT NULL CHECK (operation_type IN ('create', 'update', 'delete')),
  desired_generation bigint      NOT NULL,
  requested_by       text        NOT NULL,
  correlation_id     text        NOT NULL,
  idempotency_key    text,
  status             text        NOT NULL CHECK (status IN ('accepted', 'in_progress', 'completed', 'failed')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  completed_at       timestamptz
);
CREATE UNIQUE INDEX item_operation_idempotency_key
  ON sample.item_operation (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX item_operation_resource ON sample.item_operation (resource_id, created_at);

CREATE TABLE sample.item_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE,
  resource_id  text        NOT NULL,
  subject      text        NOT NULL,
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX item_outbox_pending   ON sample.item_outbox (sequence)     WHERE published_at IS NULL;
CREATE INDEX item_outbox_published ON sample.item_outbox (published_at) WHERE published_at IS NOT NULL;

CREATE TABLE sample.item_inbox (
  message_id  text        PRIMARY KEY,
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX item_inbox_received ON sample.item_inbox (received_at);
```

O limite de 262144 bytes (256 KiB) é o valor de referência de `SCHEMA.md` e pode ser ajustado por contrato. `pg_column_size` mede o valor armazenado, que pode estar comprimido; o limite da aplicação continua sendo a verificação autoritativa do tamanho do conteúdo.

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
- o banco deve usar codificação UTF-8;
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

- O nível de isolamento é **Read Committed** (padrão). Em Read Committed, um `UPDATE` que encontra a linha alterada por outra transação espera a outra terminar e **reavalia a condição `WHERE`** na versão nova. Isso sustenta o controle otimista com `resource_version` na condição.
- Nível mais alto (Repeatable Read) faria transações falharem com erro de serialização, e a aplicação precisaria repetir toda a transação. Não é adotado.
- Cada mensagem consumida pelo Manager é **uma transação**: começa com o registro no inbox e termina com a confirmação da gravação (`COMMIT`). A confirmação ao transporte ocorre depois do `COMMIT`.
- A aplicação repete a transação a partir do estado atual em caso de conflito de concorrência detectado (nenhuma linha afetada), deadlock (`40P01`) ou falha de serialização (`40001`), com limite de tentativas e atraso crescente. Esgotadas as tentativas, a mensagem não é confirmada e segue a política de retry do transporte.
- Transações são curtas e não incluem chamadas externas.
- A **linha do recurso é atualizada antes da inserção no outbox**, na mesma transação. Isso é essencial para a ordem do outbox (ver a seção do relay).

# 9. Concorrência otimista

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

- Zero linhas afetadas significa **conflito** (versão desatualizada) ou recurso inexistente. A aplicação distingue os dois casos e devolve um conflito explícito.
- A mudança apenas de `reconciliation` usa o mesmo comando sem alterar `desired`: a geração não incrementa, e `resource_version` sim (validado no DDL de referência).
- As expressões de `SET` usam os valores **anteriores** da linha, o que torna a decisão sobre a geração atômica.

# 10. Idempotência de entrada

## 10.1 Inbox

```sql
INSERT INTO sample.item_inbox (message_id) VALUES ($message_id)
ON CONFLICT DO NOTHING
RETURNING message_id;
```

Nenhuma linha retornada significa **duplicata**. O `RETURNING` exige o privilégio `SELECT` na coluna. O inbox é uma otimização (ver `SSOT.md`): sua perda ou expiração não compromete a correção.

## 10.2 Regras semânticas

- **`requested`:** o índice único parcial em `idempotency_key` (tabela de Operation) rejeita a mesma solicitação repetida; a tentativa duplicada devolve a Operation já existente.
- **`observed`:** monotonia de `observed_at`.

```sql
UPDATE sample.item
   SET observed = $observed, presence = $presence, observed_at = $observed_at,
       resource_version = resource_version + 1, updated_at = now()
 WHERE resource_id = $id
   AND (observed_at IS NULL OR observed_at < $observed_at)
RETURNING resource_version;
```

Zero linhas afetadas significa observação não mais recente: a mensagem é descartada como já refletida.

- **`completed` e `failed`:** a Operation e o `failure_count` são atualizados por `actionId`; um resultado já registrado não é contado de novo.

# 11. Outbox e relay

## 11.1 Gravação

A mensagem é inserida no outbox **na mesma transação** da alteração que a originou, depois do `UPDATE` do recurso:

```sql
INSERT INTO sample.item_outbox (message_id, resource_id, subject, payload)
VALUES ($message_id, $id, $subject, $payload);
```

## 11.2 Ordem por recurso

O `sequence` é atribuído no momento da inserção. Como a transação atualiza primeiro a linha do recurso, **duas transações sobre o mesmo recurso são serializadas pelo bloqueio da linha**: a segunda só insere no outbox depois que a primeira confirmou. Logo, para um mesmo recurso, a ordem de `sequence` é a ordem de confirmação (validado com duas sessões concorrentes).

Entre recursos diferentes não há garantia de ordem, e ela não é necessária.

## 11.3 Leitura pelo relay

O relay lê por consulta periódica, **sem marca-d'água por sequência**:

```sql
SELECT sequence, message_id, subject, payload
  FROM sample.item_outbox
 WHERE published_at IS NULL
 ORDER BY sequence
 LIMIT $lote
 FOR UPDATE;
```

Motivo: uma transação pode confirmar depois de outra de `sequence` maior (recursos diferentes), de modo que uma mensagem de `sequence` menor pode aparecer depois. Selecionar sempre por `published_at IS NULL` garante que ela seja encontrada na rodada seguinte; guardar apenas "o último sequence publicado" a perderia (validado).

## 11.4 Uma instância ativa

Para preservar a ordem por recurso, **uma única instância do relay publica por vez**, por tabela de outbox, usando trava consultiva de sessão:

```sql
SELECT pg_try_advisory_lock(hashtext('sample.item_outbox'));
```

A instância que não obtém a trava aguarda e tenta de novo. A trava é liberada quando a conexão cai, o que habilita o failover. A trava é **de sessão**: exige conexão direta ou *pooling* de sessão. *Pooling* em modo de transação invalida a garantia e deve ser evitado no relay (validar no ambiente).

**`FOR UPDATE SKIP LOCKED` não é usado.** Em uma sobreposição de duas instâncias, `SKIP LOCKED` faz a segunda pular o lote da primeira e publicar linhas posteriores antes das anteriores (validado). A documentação do PostgreSQL também classifica `SKIP LOCKED` como visão inconsistente, adequada a filas em que a ordem não importa. Se a vazão exigir mais de uma instância, a alternativa é particionar o relay por hash de `resource_id`, com `SKIP LOCKED` ou trava por partição, preservando a ordem por recurso.

## 11.5 Publicação e marcação

1. publicar a mensagem no transporte, com a sua identidade (`message_id`) como chave de deduplicação do transporte;
2. confirmar a publicação;
3. marcar `published_at` das mensagens publicadas.

```sql
UPDATE sample.item_outbox SET published_at = now() WHERE sequence = ANY($sequences);
```

Uma falha entre os passos 2 e 3 provoca republicação (entrega *pelo menos uma vez*). A deduplicação do transporte e a idempotência dos consumidores a absorvem.

Uma mensagem **não** é marcada como publicada sem a confirmação do transporte. Em falha de publicação, ela permanece pendente, e o relay insiste com atraso crescente, sem pular a mensagem.

## 11.6 Atraso

O atraso do relay é observável: idade da mensagem pendente mais antiga (`now() - min(created_at)` onde `published_at` é nulo) e quantidade pendente.

# 12. Retenção

| Tabela | Regra |
|---|---|
| Outbox | Remover mensagens publicadas após o prazo de retenção (`DELETE` em lote por `published_at`) |
| Inbox | Remover registros mais antigos que a janela definida pelo ambiente (`DELETE` em lote por `received_at`) |
| Operation | Remover operações concluídas após o prazo de retenção; o que deve durar mais pertence à auditoria |

A remoção é feita por uma **identidade de manutenção** própria, com `DELETE` apenas nessas tabelas. Os serviços de runtime não removem inbox, outbox nem operações.

O particionamento por tempo é uma evolução possível, adotada apenas com volume medido: remover uma partição é muito mais barato que `DELETE` em massa. A restrição é que chaves únicas e primárias de uma tabela particionada devem incluir a chave de partição, o que enfraquece a unicidade global de `message_id`. Por isso o particionamento só é adotado se a idempotência continuar garantida pelas regras semânticas (e não pelo inbox).

# 13. Remoção de recursos

A remoção segue `SSOT.md`:

1. o pedido de remoção atualiza o recurso para `lifecycle = absent`, `phase = Deleting` e registra o outbox (`desired`);
2. após a convergência (`presence = absent`), o Manager remove o registro com `DELETE` em uma transação que também registra o outbox (`updated`);
3. a Operation permanece até a sua retenção, e por isso não há chave estrangeira entre `<tipo>_operation` e `<tipo>`.

# 14. Segurança

## 14.1 Papéis

Um papel por serviço, sem login nos papéis de função: o login é concedido pela infraestrutura, com credencial própria.

| Papel | Privilégios |
|---|---|
| `<módulo>_<tipo>_manager` | `SELECT`, `INSERT`, `UPDATE` e `DELETE` em `<tipo>`; `SELECT`, `INSERT` e `UPDATE` em `<tipo>_operation`; `SELECT` e `INSERT` em `<tipo>_outbox` e `<tipo>_inbox` |
| `<módulo>_<tipo>_api` | `SELECT` por coluna em `<tipo>` e `<tipo>_operation`, sem as colunas internas de controle |
| `<módulo>_relay` | `SELECT` em `<tipo>_outbox` e `UPDATE (published_at)` |
| `<módulo>_maintenance` | `SELECT` e `DELETE` em outbox, inbox e operation |
| Proprietário (administração) | Dono dos objetos, criação e migração; não é usado por serviços de runtime |

```sql
REVOKE ALL ON SCHEMA sample FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA sample FROM PUBLIC;
GRANT USAGE ON SCHEMA sample TO sample_item_manager, sample_item_api, sample_relay, sample_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON sample.item           TO sample_item_manager;
GRANT SELECT, INSERT, UPDATE         ON sample.item_operation TO sample_item_manager;
GRANT SELECT, INSERT                 ON sample.item_outbox    TO sample_item_manager;
GRANT SELECT, INSERT                 ON sample.item_inbox     TO sample_item_manager;

GRANT SELECT (resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
              resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at)
      ON sample.item TO sample_item_api;
GRANT SELECT (operation_id, resource_id, operation_type, desired_generation, status,
              created_at, updated_at, completed_at)
      ON sample.item_operation TO sample_item_api;

GRANT SELECT ON sample.item_outbox TO sample_relay;
GRANT UPDATE (published_at) ON sample.item_outbox TO sample_relay;

GRANT SELECT, DELETE ON sample.item_outbox, sample.item_inbox, sample.item_operation TO sample_maintenance;
```

Pontos relevantes, verificados no DDL de referência:

- o PostgreSQL não concede privilégios padrão em tabelas e em schemas, mas o `REVOKE` explícito de `PUBLIC` é mantido como defesa contra mudanças de padrão e de herança;
- o `FOR UPDATE` do relay exige o privilégio `UPDATE`, que ele possui somente na coluna `published_at`;
- o Manager **não** possui `DELETE` em outbox, inbox e operation, nem privilégio de alterar a estrutura;
- a API não lê `failure_count` nem nenhuma tabela de controle de mensagens.

Em cada alteração do modelo, a matriz de privilégios é revisada contra a matriz de identidades de `RESOURCE-CONTROL-SECURITY.md`.

## 14.2 Isolamento por tipo

O isolamento entre tipos de recurso é obtido por privilégios por tabela. **Row-Level Security não é adotada**: a combinação de uma tabela por tipo e privilégios por tabela cumpre o isolamento com menos mecanismos. Se um tipo precisar de isolamento por linha (por exemplo, por tenant), ele é tratado explicitamente no contrato e a RLS é reavaliada.

## 14.3 Conexão, repouso e segredos

- conexões usam TLS fora do ambiente local, com validação do certificado do servidor, e preferencialmente autenticação mútua para serviços;
- este documento **não assume** criptografia nativa do banco em repouso: a proteção em repouso é exigida da plataforma (volume ou equivalente) e deve ser validada no ambiente, conforme a classificação dos dados;
- credenciais são fornecidas por gestão de segredos, nunca versionadas;
- parâmetros de comandos e valores de colunas `confidential` não são registrados em log (configuração de log do servidor e do cliente);
- mensagens de erro do banco não são devolvidas ao cliente externo.

# 15. Migrações

- migrações são **versionadas, revisadas e executadas por infraestrutura** com o proprietário dos objetos. Serviços de runtime não executam DDL;
- a estrutura de cada tipo é gerada do modelo; uma mudança no modelo é aplicada a todos os tipos pelo mesmo mecanismo;
- a evolução segue **expandir → migrar → contrair**: adicionar de forma compatível, migrar o conteúdo e só então remover o antigo. É a tradução, para o banco, da sequência de `SCHEMA.md`;
- uma mudança `MAJOR` de contrato exige conversão na leitura durante a coexistência e migração do conteúdo gravado e da mensagem retida, com republicação preservando geração e conteúdo;
- `schema_version` de cada registro indica o que ainda não foi migrado;
- DDL que bloqueia a tabela por muito tempo (reescrita completa) deve ser avaliado antes, e executado em janela ou por técnica de baixo bloqueio, a validar no ambiente.

# 16. Backup e recuperação

- cópia de segurança com **recuperação a um ponto no tempo (PITR)**: backup base mais arquivamento contínuo de WAL, armazenados fora do servidor do banco;
- a **replicação não é cópia de segurança**: um erro lógico é replicado imediatamente para os standbys;
- a restauração é **testada periodicamente**, e o resultado é registrado;
- os objetivos de recuperação (ponto e tempo) são parâmetros do ambiente;
- versões recentes do PostgreSQL suportam backups incrementais; o seu uso é uma decisão do ambiente;
- após uma restauração a um ponto anterior, o Manager reavalia o estado e republica o `desired` quando necessário. A geração não retrocede, e os consumidores tratam republicações como idempotentes (`SSOT.md`).

# 17. Alta disponibilidade

- o banco usa replicação com failover definidos pela infraestrutura;
- o failover interrompe transações em andamento: a unidade atômica é repetida a partir do estado atual, e a mensagem só é confirmada ao transporte após o `COMMIT`;
- o relay reabre a trava consultiva na nova instância e republica o que estiver pendente;
- com o banco indisponível, o Manager não aceita novos pedidos nem atualiza o estado, e o loop continua sobre o `desired` já publicado (`SSOT.md`). Isso deve gerar alerta;
- a leitura em réplica pela API aceita atraso de replicação; leituras que precisam refletir a própria escrita (por exemplo, a resposta de uma criação) devem usar o primário.

# 18. Observabilidade

Medir, sem expor dados sensíveis:

```text
idade da mensagem pendente mais antiga no outbox
quantidade pendente no outbox
tamanho de inbox, outbox e operation
transações repetidas por conflito, deadlock ou serialização
esperas por bloqueio de linha
duração das transações do Manager
tamanho das tabelas e dos índices
atraso de replicação
atraso do arquivamento de WAL
idade do último backup base e do último teste de restauração
quantidade de recursos por phase, em Failed e com reconciliação suspensa
```

# 19. Anti-padrões

- escrever no banco por serviço que não seja o Manager;
- registrar o outbox sem atualizar antes a linha do recurso na mesma transação (quebra a ordem por recurso);
- usar marca-d'água de sequência para publicar o outbox;
- usar `FOR UPDATE SKIP LOCKED` no relay ordenado;
- publicar por mais de uma instância sem partição determinística por recurso;
- relay em *pooling* de transação com trava consultiva de sessão;
- confirmar a mensagem ao transporte antes do `COMMIT`;
- índice GIN por padrão;
- usar `jsonb` para o que participa de concorrência, unicidade ou consulta do loop;
- tratar o texto de um `jsonb` como original (assinatura, hash);
- documentos grandes em um único registro;
- conceder `DELETE` em outbox, inbox ou operation ao Manager;
- executar DDL por serviço de runtime;
- confiar na replicação como cópia de segurança.

# 20. Checklist

- [ ] A versão do PostgreSQL está fixada no ambiente?
- [ ] As quatro tabelas do tipo são geradas do modelo?
- [ ] `lifecycle`, `reconciliation`, `presence` e `phase` possuem `CHECK`?
- [ ] `resource_id`, tamanho e tipo dos `jsonb` possuem `CHECK`?
- [ ] A atualização usa `resource_version` na condição e confere as linhas afetadas?
- [ ] A geração só incrementa quando a especificação muda?
- [ ] A transação atualiza a linha antes de inserir no outbox?
- [ ] O relay usa uma instância ativa por trava consultiva, sem marca-d'água e sem `SKIP LOCKED`?
- [ ] O relay só marca `published_at` após a confirmação do transporte?
- [ ] A matriz de privilégios corresponde à matriz de identidades do `SECURITY.md`?
- [ ] `PUBLIC` está sem privilégios, e o Manager sem `DELETE` em outbox, inbox e operation?
- [ ] Existe identidade de manutenção para a retenção?
- [ ] TLS está habilitado fora do ambiente local, e a proteção em repouso foi validada?
- [ ] Parâmetros e colunas `confidential` não aparecem em log?
- [ ] Existe PITR e teste periódico de restauração?
- [ ] As migrações seguem expandir → migrar → contrair, por infraestrutura?

# 21. Verificação do DDL de referência

O DDL e os comportamentos descritos neste documento foram exercitados em um contêiner descartável com **PostgreSQL 18.6**, sem dados reais:

- restrições (`CHECK`) de `resource_id`, de enumerações, de tipo `jsonb` e da coerência entre `presence` e `observed_at`;
- concorrência otimista (versão antiga não altera linhas), geração não incrementa com a mesma especificação (inclusive com ordem de chaves diferente) nem ao mudar só `reconciliation`, e incrementa e zera `failure_count` quando a especificação muda;
- monotonia de `observed_at`;
- duplicata do inbox com `ON CONFLICT DO NOTHING ... RETURNING`;
- índice único parcial de `idempotency_key`;
- privilégios: leitura por coluna da API, negação de `PUBLIC`, negação de `DELETE` e de DDL ao Manager, `UPDATE (published_at)` do relay e `DELETE` da manutenção;
- ordem do outbox por recurso entre duas sessões concorrentes, visibilidade fora de ordem entre recursos diferentes, exclusão mútua da trava consultiva e publicação fora de ordem com `SKIP LOCKED`.

**Não foi verificado:** carga e desempenho, relay real com transporte, failover, PITR, criptografia em repouso, *pooling* de conexões e o custo de DDL em tabelas grandes. Esses pontos devem ser validados no ambiente.

# 22. Fontes técnicas

A implementação deste documento utiliza como referência a documentação oficial do PostgreSQL:

- Tipos JSON: https://www.postgresql.org/docs/current/datatype-json.html
- Isolamento de transações: https://www.postgresql.org/docs/current/transaction-iso.html
- INSERT e `ON CONFLICT`: https://www.postgresql.org/docs/current/sql-insert.html
- SELECT e cláusulas de bloqueio: https://www.postgresql.org/docs/current/sql-select.html
- Privilégios: https://www.postgresql.org/docs/current/ddl-priv.html
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
