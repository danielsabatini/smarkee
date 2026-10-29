# Especificação do SSOT

> **Escopo:** o que o SSOT guarda, com quais garantias de gravação, concorrência, idempotência, publicação, segurança, evolução e recuperação.
>
> **Papel:** Fonte de Verdade do modelo e das garantias do SSOT.
>
> **Responsabilidade:** Definir o modelo lógico, as invariantes e o comportamento de gravação do SSOT de forma independente de produto, domínio, fornecedor e tecnologia de armazenamento. A implementação em uma tecnologia específica pertence a um documento próprio (`POSTGRESQL.md`).

# 1. Introdução

O SSOT (*Single Source of Truth*) é o registro durável da intenção e do estado consolidado de cada recurso gerenciado pelo Resource Control Loop (`RESOURCE-CONTROL-LOOP.md`).

A arquitetura separa quatro responsabilidades:

```text
MESSAGING.md
    ↓
define a semântica das mensagens

SCHEMA.md
    ↓
define as regras dos contratos

SSOT.md
    ↓
define o que é guardado e as garantias de gravação

POSTGRESQL.md
    ↓
define como a implementação de referência cumpre essas garantias
```

# 2. Objetivo

- definir de forma única o que o SSOT guarda e o que não guarda;
- garantir que a intenção, o estado consolidado e as mensagens a publicar sejam gravados de forma atômica;
- tornar a gravação segura sob repetição, concorrência e falha parcial;
- impedir que o armazenamento defina o significado do domínio;
- permitir trocar a tecnologia de armazenamento sem alterar o modelo.

# 3. Fonte de Verdade e Precedência

```text
AGENTS.md
    >
SSOT.md
    >
documento de implementação do armazenamento (POSTGRESQL.md)
    >
implementação
```

`MESSAGING.md` é a fonte de verdade das mensagens e do envelope. `SCHEMA.md` é a fonte de verdade dos contratos formais. `RESOURCE-CONTROL-LOOP.md` define o padrão de convergência. Este documento não redefine esses temas: define como o resultado deles é gravado.

O agent `ssot` é uma instrução de metodologia e aponta para este documento. Ele não é fonte de regras.

# 4. Princípios

- **O dado precede o armazenamento.** Primeiro o significado, as invariantes e o ciclo de vida; só depois a representação.
- **Dois escritores com fronteiras estritas.** A API escreve a intenção e a admissão; o Controller escreve a observação e a convergência reconciliada (`RESOURCE-CONTROL-LOOP.md` §3.5).
- **Atomicidade transacional por ciclo.** Toda alteração de estado grava a linha do recurso e a respectiva mensagem no outbox em uma única transação atômica.
- **Correção por regras semânticas, não por memória de entrega.** Idempotência não depende de lembrar indefinidamente todas as mensagens passadas.
- **Segurança por padrão.** Acesso mínimo, privilégios segregados por papel de banco, dado classificado, nada sensível em log.
- **Simplicidade.** Guardar somente o que o controle declarativo do recurso exige.

# 5. Agnosticismo

O modelo não depende de produto, domínio, fornecedor externo nem tecnologia de armazenamento. Conceitos de um fornecedor específico não entram no modelo; usam-se `externalResourceId`, `externalReference` e `providerReference`.

Um tipo de recurso concreto é descrito por um contrato de domínio (`SCHEMA.md`), e não por este documento. Os exemplos usam nomes neutros.

# 6. Escopo: o que é guardado

## 6.1 Guardado

- a identidade e a intenção do recurso (`desired`, `lifecycle`, `reconciliation`, `requestedBy`, `correlationId`);
- o último estado observado e o seu resultado factual (`observed`, `presence`, `observedAt`);
- o estado consolidado da convergência (`phase`, `conditions`);
- as gerações (`desiredGeneration`, `observedGeneration`) e a versão para controle otimista (`resourceVersion`);
- as mensagens aguardando publicação pelo Publisher (outbox transacional);
- o registro de idempotência de admissão da API (`idempotencyKey`, `requestDigest`, `resourceId`).

Não existe inbox: a idempotência é garantida pelas regras semânticas do ciclo e pela deduplicação da admissão.

## 6.2 Não guardado

- o **histórico completo** de observações e de mudanças: pertence ao registro de auditoria (`Stream AUDIT`), que é um consumidor assíncrono e não participa da operação do loop;
- segredos: apenas referências seguras (`SCHEMA.md`);
- projeções de interface, métricas e relatórios: são construídos por consumidores assíncronos.

# 7. Modelo Lógico

Para cada tipo de recurso existem **três conjuntos de registros** no SSOT, com fronteiras explícitas de persistência:

1. **Resource (`<tipo>`):** o estado consolidado (um registro por recurso gerenciado). Contém o estado pretendido (`desired`), o estado observado (`observed`), a fase (`phase`), as condições (`conditions`) e as gerações;
2. **Outbox (`<tipo>_outbox`):** a fila transacional de saída (uma mensagem por linha) aguardando entrega ao NATS pelo Publisher;
3. **Idempotência (`<tipo>_idempotency`):** deduplicação de requisições de admissão da API por chave e solicitante (`requested_by`, `idempotency_key`, `request_digest`, `resource_id`).

Não existem tabelas de `Operation` nem de `ActionResult` (extintas pelas decisões 0096, 0098 e 0101): a API admite síncrono respondendo diretamente com o `Resource`, e as ações contra sistemas externos ocorrem em ciclo local do Controller.

## 7.1 Resource

Registro consolidado de um recurso. Existe uma tabela por tipo de recurso, com a seguinte estrutura conceitual:

| Elemento | Significado |
|---|---|
| Identidade | `resourceId` estável, opaco (UUIDv7) e válido conforme `SCHEMA.md` |
| Intenção | `lifecycle`, `reconciliation` e o conteúdo declarativo de `desired` |
| Causa | `requestedBy` e `correlationId` do pedido que gerou a geração atual |
| Observação | último `observed`, `presence` e `observedAt` lidos do sistema externo |
| Consolidação | `phase` e `conditions` |
| Versionamento | `desiredGeneration`, `observedGeneration` e `resourceVersion` |
| Falhas | contagem de falhas consecutivas da geração corrente (`failureCount`) |
| Contrato | `schemaVersion` do contrato com que o conteúdo foi gravado |
| Tempo | `createdAt` e `updatedAt` |

## 7.2 Idempotência da Admissão

Registro de deduplicação das escritas submetidas à API com o cabeçalho `Idempotency-Key` (`RESOURCE-CONTROL-LOOP.md` §6.1.1):

- `requestedBy`: identidade do solicitante autenticado (a chave é escopada ao solicitante);
- `idempotencyKey`: a chave fornecida pelo cliente;
- `requestDigest`: hash criptográfico do corpo canônico da requisição;
- `resourceId`: o recurso associado;
- `createdAt`: instante da admissão inicial.

Repetir a mesma chave com o mesmo `requestDigest` devolve o `Resource` atual sem reinserção ou republicação. Reutilizar a chave com payload divergente é rejeitado com erro HTTP `422 IdempotencyKeyReused`. Registros com mais de 24 horas são expurgados pelo utilitário de retenção operacional (`scripts/dev/retention`, decisão 0101).

## 7.3 Outbox

Registro de cada mensagem que deve ser publicada (a *caixa de saída* do SSOT), gravado **na mesma unidade atômica** da alteração que a originou (`RESOURCE-CONTROL-LOOP.md` §6.6.1). Contém a identidade da mensagem (`messageId`), o Subject NATS (`<messageType>.<module>.<resourceType>.<resourceId>`), o payload JSON completo, a ordem de inserção e o instante de publicação (`publishedAt`).

Linhas publicadas são mantidas por 24 horas para auditoria e observabilidade, e então expurgadas pelo utilitário de retenção operacional (`scripts/dev/retention`, decisão 0101).

# 8. Dicionário de Dados

Estrutura canônica do registro do Resource no SSOT:

| Campo | Definição | Tipo conceitual | Obrigatório | Mutabilidade | Escritor | Sensibilidade |
|---|---|---|---|---|---|---|
| `resourceId` | Identidade estável do recurso | UUIDv7 | Sim | Imutável | API (na criação) | `internal` |
| `lifecycle` | Intenção de existência | enumeração: `present`, `absent` | Sim | Mutável | API | `internal` |
| `reconciliation` | Controle da reconciliação (`active` ou `suspended`) | enumeração: `active`, `suspended` | Sim | Mutável | API / Controller | `internal` |
| `desired` | Conteúdo declarativo pretendido | objeto JSON do contrato | Sim | Mutável | API | por campo do contrato |
| `desiredGeneration` | Versão lógica da intenção declarativa | inteiro crescente | Sim | Automática | API | `internal` |
| `requestedBy` | Solicitante da geração vigente | identificador opaco | Sim | Mutável | API | `internal` |
| `correlationId` | Identificador de correlação do pedido | identificador opaco | Sim | Mutável | API | `internal` |
| `resourceVersion` | Versão persistida para controle otimista | inteiro ou string opaca | Sim | Automática | API / Controller | `internal` |
| `observed` | Último estado lido do sistema externo | objeto JSON do contrato | Não | Mutável | Controller | por campo do contrato |
| `presence` | Resultado factual da observação | enumeração: `present`, `absent`, `unknown` | Não | Mutável | Controller | `internal` |
| `observedAt` | Instante em que a observação ocorreu | timestamp UTC | Não | Mutável | Controller | `internal` |
| `phase` | Fase consolidada de ciclo de vida | enumeração: `Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting` | Sim | Mutável | API (criação) / Controller | `internal` |
| `conditions` | Fatos consolidados da convergência | lista de condition (Kubernetes-like) | Sim | Mutável | Controller | `internal` |
| `failureCount` | Falhas consecutivas de ação da geração vigente | inteiro | Sim | Automática | Controller | `internal` |
| `observedGeneration` | Última geração cuja convergência foi confirmada | inteiro crescente | Não | Automática | Controller | `internal` |
| `schemaVersion` | Versão do contrato com que o conteúdo foi gravado | `MAJOR.MINOR` | Sim | Mutável | API | `internal` |
| `createdAt` | Instante de admissão inicial | timestamp UTC | Sim | Imutável | API | `internal` |
| `updatedAt` | Instante da última gravação durável | timestamp UTC | Sim | Automática | API / Controller | `internal` |

Campos de `desired` e `observed` herdam a sensibilidade declarada no contrato do recurso (`SCHEMA.md`). Um campo `confidential` nunca é exposto em log, erro ou métrica.

# 9. Invariantes

1. **`resourceId` é único e imutável** dentro do tipo de recurso.
2. **`desiredGeneration` só aumenta**, e somente quando a **especificação** pretendida muda. Alterar apenas o controle de `reconciliation` não a incrementa.
3. **`resourceVersion` muda a cada gravação** do registro e é a base do controle de concorrência otimista.
4. **Toda alteração que gera mensagem registra a mensagem no outbox na mesma unidade atômica.** Não existe o estado "alterado no banco, mas não registrado para publicar".
5. **`observed` reflete a realidade factual:** `presence = unknown` representa leitura falha ou inconclusiva e nunca é tratado como ausente (`absent`).
6. **`phase` e `failureCount` são derivados** das regras de convergência e das invariantes, nunca de entrada arbitrária do cliente.
7. **O SSOT não executa chamadas externas** e não depende de resposta de provedores externos para comitar.
8. **Remoção física só ocorre após a convergência factual da exclusão** (`presence = absent`).
9. **As unidades atômicas sobre um mesmo recurso são serializadas** por bloqueio exclusivo da linha (`SELECT ... FOR UPDATE`). Duas transações nunca alteram o mesmo recurso concorrentemente.
10. **Uma geração publicada nunca é reutilizada com outro conteúdo.**
11. **O registro reflete o último `desired` registrado no outbox.**
12. **`observedGeneration` só cresce e nunca ultrapassa `desiredGeneration`.** Uma geração só é confirmada por uma observação convergida realizada após o início daquela geração.

# 10. Unidade Atômica de Gravação

O SSOT possui dois escritores com transações bem delimitadas:

## 10.1 Admissão pela API

Cada escrita submetida pelo cliente é processada em uma transação atômica síncrona:

1. **Trava consultiva:** adquire trava por chave (`pg_advisory_xact_lock`) para serializar verificações de regras de negócio, como unicidade de nome e cota por dono;
2. **Concorrência otimista (em alterações):** adquire bloqueio da linha (`SELECT ... FOR UPDATE`) e confere se a `resourceVersion` enviada coincide com a persistida; se divergente, a transação reverte e a API responde HTTP `409 Conflict`;
3. **Idempotência:** verifica se a `Idempotency-Key` já existe na tabela de idempotência para aquele solicitante; se existir com o mesmo `requestDigest`, devolve o recurso atual; se existir com hash diferente, rejeita com HTTP `422 IdempotencyKeyReused`;
4. **Gravação do Recurso:** insere o novo recurso com `phase = Pending` e `desiredGeneration = 1` (na criação), ou incrementa `desiredGeneration` e atualiza `desired`, `lifecycle` e causa (`requestedBy`, `correlationId`);
5. **Gravação da Idempotência:** insere o registro na tabela `<tipo>_idempotency`;
6. **Gravação no Outbox:** insere no `<tipo>_outbox` a mensagem `desired` com Subject `desired.<module>.<resourceType>.<resourceId>` e `emitter: api`;
7. **COMMIT:** comita a transação e responde síncrono `201 Created` (ou `200 OK` / `202 Accepted` na deleção) com a representação consolidada do `Resource`.

Se o banco estiver indisponível ou a transação falhar, nada é gravado e a API responde `503 Service Unavailable` com `Retry-After: 5`.

## 10.2 Ciclo de Reconciliação pelo Controller

A cada ciclo de reconciliação de um recurso (`RESOURCE-CONTROL-LOOP.md` §3.3):

1. **Acesso exclusivo:** abre transação e adquire bloqueio da linha (`SELECT ... FOR UPDATE`);
2. **Leitura do estado vigente:** lê `desired`, `lifecycle`, `reconciliation` e `desiredGeneration`; se `reconciliation == suspended`, encerra o ciclo sem agir;
3. **Observação e Ação:** observa o sistema externo via adaptador de leitura; aplica `decide(desired, observed)`; se houver ação necessária, executa via adaptador de escrita e reobserva imediatamente;
4. **Consolidação:** calcula o novo estado:
   - se a reobservação convergiu: `observedGeneration = desiredGeneration`, `phase = Ready`, `conditions` com `Ready=True`;
   - se a remoção convergiu (`lifecycle = absent` e `presence = absent`): apaga fisicamente a linha do recurso e insere no outbox o `updated` com `removed = true`;
5. **Gravação no Outbox:** insere a mensagem `updated` com Subject `updated.<module>.<resourceType>.<resourceId>` e `emitter: controller`;
6. **COMMIT:** grava duravelmente o novo estado consolidado e a mensagem de saída na mesma transação.

Se ocorrer erro de infraestrutura ou exceção inesperada, a transação é revertida (`ROLLBACK`) e nenhum estado parcial é persistido.

## 10.3 Limite de Falhas e Suspensão da Reconciliação

Toda falha de execução de ação no sistema externo incrementa `failureCount` na geração vigente e registra a condition correspondente (`Ready=False`, `ActionFailed`, trazendo o motivo e o detalhe em `message`).

Quando `failureCount` atinge o `failureLimit` do contrato do recurso (padrão de 5 falhas consecutivas):

1. O Controller define `phase = Failed` e grava a condition `Ready=False` com motivo `FailureLimitReached`;
2. Atualiza `reconciliation = suspended` no Resource;
3. Insere no `<tipo>_outbox` a mensagem `desired` com `reconciliation = suspended` na mesma geração (`emitter: controller`), anunciando a suspensão no NATS (Stream `DESIRED`);
4. A reconciliação do recurso cessa imediatamente, impedindo laços infinitos contra o sistema externo ou sobrecarga de requisições rejeitadas.

## 10.4 Nova Geração

Quando a especificação declarativa do recurso muda na admissão, `desiredGeneration` é incrementado, `failureCount` é zerado e a reconciliação volta a `active` (salvo pedido explícito em contrário). Alterações em `reconciliation` ou campos não gerenciados não incrementam a geração.

# 11. Concorrência

O controle de concorrência opera em dois níveis:

1. **Para o cliente (concorrência otimista):** operações de alteração (`PATCH` e `DELETE`) informam a `resourceVersion` lida. Caso a versão no banco divirja, a requisição é rejeitada com `409 Conflict`. Nenhuma alteração sobrescreve outra silenciosamente;
2. **Entre processos e workers (serialização pessimista):** no início de qualquer ciclo de admissão ou de reconciliação, a linha do recurso é bloqueada com `SELECT ... FOR UPDATE`. Uma admissão que chegue durante um ciclo de reconciliação aguarda o `COMMIT`; o ciclo seguinte processará a nova geração admitida.

# 12. Idempotência e Retenção

A correção sob reentrega ou repetição não depende de memória infinita de eventos:

| Camada | Mecanismo | Política de Retenção |
|---|---|---|
| **Admissão da API** | Tabela `<tipo>_idempotency` com `requestedBy`, `idempotencyKey` e `requestDigest`. | Retenção de 24 horas via utilitário de expurgo (`scripts/dev/retention`). |
| **Ciclo do Controller** | Reavaliação factual fresca a cada ciclo sob `FOR UPDATE`; ação idempotente com chave de correlação no provedor externo; Workqueue com single-flight por recurso. | Não depende de tabela histórica de ações: o estado do provedor externo e o SSOT são as fontes da verdade. |
| **Outbox** | Tabela `<tipo>_outbox` com entrega sequencial pelo Publisher e deduplicação no NATS via `messageId`. | Retenção de 24 horas para mensagens já publicadas (`published_at IS NOT NULL`), expurgadas pelo utilitário de retenção. |

A chave de idempotência é estritamente escopada ao solicitante autenticado: chaves idênticas enviadas por usuários diferentes são totalmente isoladas e nunca colidem.

# 13. Outbox e o Publisher

A entrega de mensagens registradas no outbox é responsabilidade do componente **Publisher** (`RESOURCE-CONTROL-LOOP.md` §6.6), que opera como processo dedicado com menor privilégio:

- a entrega é do tipo *pelo menos uma vez*: falhas antes da confirmação geram reenvio;
- a publicação é **estritamente sequencial** por outbox: a próxima mensagem só é enviada após a confirmação do NATS (ACK) da anterior;
- **uma única instância ativa** do Publisher opera por tipo de recurso, coordenada por trava consultiva de sessão no banco;
- toda mensagem leva seu `messageId` no cabeçalho `Nats-Msg-Id` para deduplicação transparente no broker;
- a ordem de gravação no SSOT é rigorosamente preservada na publicação;
- o Publisher **não executa regras de negócio**: apenas lê linhas com `published_at IS NULL`, entrega ao broker e atualiza `published_at = now()`.

# 14. Ciclo de Vida do Registro

| Etapa | Gravação no SSOT |
|---|---|
| **Criação** | `Resource` criado com `phase = Pending`, `lifecycle = present`, `desiredGeneration = 1`; mensagem `desired` no outbox; registro em `<tipo>_idempotency`. |
| **Reconciliação** | `phase = Reconciling`; ao convergir a reobservação, `phase = Ready`, `observedGeneration = desiredGeneration`, conditions atualizadas; mensagem `updated` no outbox. |
| **Alteração** | Novo `desiredGeneration`, `failureCount = 0`, `reconciliation = active`; mensagem `desired` no outbox. |
| **Falha de Ação** | Incremento de `failureCount`, condition `ActionFailed`; ao atingir `failureLimit`, `phase = Failed`, `reconciliation = suspended` e mensagem `desired` suspensa no outbox. |
| **Remoção Solicitada** | `lifecycle = absent`, `phase = Deleting`; mensagem `desired` no outbox. Se houver dependentes ativos, permanece em `Deleting` com `DeletionBlockedByDependents`. |
| **Remoção Convergida** | Ao confirmar `presence = absent` no sistema externo, o registro é **fisicamente excluído** do SSOT e um `updated` com `removed = true` é gravado no outbox. |

# 15. Leitura e Consistência

- a API atende consultas e listagens através de **views versionadas** (ex: `<tipo>_v1`), garantindo desacoplamento entre o armazenamento físico e o contrato de exposição (`POSTGRESQL.md`);
- a leitura reflete o estado durável gravado. Como a convergência externa é assíncrona, a leitura reflete o progresso em `phase`, `observedGeneration` e `conditions`;
- o Controller nunca consulta views para tomar decisões de reconciliação: lê diretamente a linha do recurso sob bloqueio `FOR UPDATE` e consulta a realidade factual do sistema externo.

# 16. Segurança

O acesso ao SSOT aplica rigorosamente o princípio do menor privilégio (`RESOURCE-CONTROL-SECURITY.md`):

| Papel / Componente | Permissões no Banco | Restrições |
|---|---|---|
| **API** | `INSERT` e `UPDATE` nos campos de admissão do Resource; `INSERT` no `<tipo>_idempotency`; `INSERT` no `<tipo>_outbox`; `SELECT` nas views versionadas. | Não altera campos de observação/convergência; não lê nem escreve no provedor externo; não publica direto no broker. |
| **Controller** | `SELECT ... FOR UPDATE` no Resource; `UPDATE` nos campos de observação, condições e convergência; `DELETE` no Resource (somente após remoção confirmada); `INSERT` no `<tipo>_outbox`. | Não atende requisições HTTP do cliente; não acessa `<tipo>_idempotency`. |
| **Publisher** | `SELECT` e `UPDATE` (`published_at`) no `<tipo>_outbox`. | Não acessa a tabela do Resource nem executa regras de negócio. |
| **Manutenção / Retenção** | `SELECT` e `DELETE` em `<tipo>_outbox` e `<tipo>_idempotency` com credencial de manutenção (`*_maintenance_login`). | Somente o utilitário `scripts/dev/retention`; nenhum papel de runtime possui permissão de `DELETE` nestas tabelas. |
| **Migrações (DDL)** | Administrador de banco durante etapa de deployment / CI/CD. | Nenhum papel de runtime possui permissões de DDL (`CREATE`, `ALTER`, `DROP`). |

Dados confidenciais e credenciais seguem `SCHEMA.md`: segredos nunca são armazenados em texto puro no SSOT, trafegando apenas por referências seguras.

# 17. Evolução e Migração

- a estrutura de cada tipo de recurso é versionada em migrações SQL no próprio módulo da feature (`features/<módulo>/<tipo>/migrations/`);
- mudanças compatíveis de contrato (`MINOR`) não exigem migração do JSON gravado;
- mudanças incompatíveis (`MAJOR`) seguem a estratégia de expansão e contração: novas colunas ou views são criadas sem quebrar leitores existentes;
- o campo `schemaVersion` gravado em cada registro permite identificar recursos criados sob versões anteriores.

# 18. Recuperação e Continuidade

O SSOT é a **fonte primária** do estado durável, das conditions e do histórico consolidado de falhas. Por isso:

- deve existir cópia de segurança periódica (backup com point-in-time recovery testado);
- a reconstrução do SSOT a partir do transporte é apenas parcial: o NATS retém a última mensagem de `desired` e `updated`, mas não substitui a durabilidade transacional do banco;
- em caso de indisponibilidade do banco, a API responde `503` com `Retry-After` e o Controller suspende reconciliações até a restauração.

## 18.1 Recuperação após restauração de backup

Restaurar o banco a um ponto no tempo anterior faz `desiredGeneration` regredir em relação às mensagens que já circularam no broker. Sem intervenção, uma nova alteração reutilizaria uma geração anterior com conteúdo diferente (violando a invariante 10).

Procedimento operacional de recuperação (com API, Publisher e Controller pausados):

1. Limpar mensagens não publicadas (`published_at IS NULL`) do outbox anteriores ao ponto restaurado;
2. Para cada recurso no SSOT, consultar o último `desired` retido no Stream `DESIRED` do NATS JetStream;
3. Se o transporte contiver uma geração maior (ou igual com conteúdo diferente), atualizar o `desiredGeneration` no SSOT para a geração do transporte + 1 e inserir no outbox o `desired` vigente do SSOT com essa nova geração;
4. Identificar e relatar recursos que existem no transporte mas não constam no backup restaurado;
5. Liberar os componentes para operação normal.

# 19. Observabilidade

Devem ser monitorados continuamente:

- idade da mensagem mais antiga pendente no outbox (`outbox_oldest_age_seconds`);
- quantidade de linhas pendentes no outbox;
- taxa de requisições de admissão com conflito (`409 Conflict`) ou reuso de idempotência inválido (`422 IdempotencyKeyReused`);
- tempo de espera pelo bloqueio exclusivo de linha (`FOR UPDATE`);
- distribuição de recursos por fase (`Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting`);
- total de recursos em estado `Failed` com reconciliação suspensa.

# 20. Anti-Padrões

- escrever no SSOT por componentes que não sejam a API ou o Controller do respectivo tipo;
- tentar atualizar o banco e publicar no broker sem utilizar o Transactional Outbox;
- confirmar ou responder sucesso ao cliente antes do `COMMIT` durável no banco;
- ler o recurso e aplicar alterações sem bloqueio exclusivo (`SELECT ... FOR UPDATE`);
- persistir credenciais ou senhas em texto puro dentro de `desired` ou `observed`;
- remover fisicamente uma linha antes da convergência factual da exclusão (`presence = absent`);
- conceder permissões de DDL (`CREATE`, `ALTER`, `DROP`) aos usuários de aplicação em runtime;
- tentar recriar tabelas de `Operation` ou `ActionResult` em desacordo com as decisões 0096 e 0098.

# 21. Checklist

- [ ] Apenas a API e o Controller escrevem no SSOT, respeitando suas respectivas colunas?
- [ ] Toda escrita que gera mensagem registra a mensagem no outbox na mesma transação atômica?
- [ ] O Controller adquire bloqueio exclusivo (`FOR UPDATE`) antes de ler e avaliar a convergência?
- [ ] A concorrência do cliente é protegida por conferência de `resourceVersion`?
- [ ] A idempotência de admissão é garantida pela tabela `<tipo>_idempotency` escopada ao solicitante?
- [ ] A retenção de outbox publicado e idempotência obedece à janela de 24 horas via credencial de manutenção?
- [ ] A remoção física só ocorre após a comprovação de ausência no sistema externo?
- [ ] `desiredGeneration` só avança quando a especificação pretendida muda?
- [ ] Nenhuma credencial de runtime possui permissões administrativas ou de DDL?

# 22. Critérios de Sucesso

O SSOT está em conformidade quando:

- falhas de rede ou de processo nunca causam divergência entre o banco de dados e as mensagens entregues ao NATS;
- duas operações concorrentes sobre o mesmo recurso nunca se sobrescrevem silenciosamente;
- repetições de requisições de admissão com a mesma chave devolvem o estado existente sem efeitos colaterais;
- o modelo e as garantias permanecem válidos independentemente do SGBD utilizado;
- o ciclo de convergência opera de forma idempotente, segura e auditável.

# 23. Referências

- [MESSAGING.md](../messaging/MESSAGING.md): semântica das mensagens e do envelope.
- [SCHEMA.md](SCHEMA.md): contratos formais, versionamento e classificação.
- [RESOURCE-CONTROL-LOOP.md](../loop/RESOURCE-CONTROL-LOOP.md): padrão de convergência declarativa.
- [RESOURCE-CONTROL-SECURITY.md](../loop/RESOURCE-CONTROL-SECURITY.md): segurança e privilégios.
- [POSTGRESQL.md](POSTGRESQL.md): implementação física de referência no PostgreSQL.

# 24. Fonte de Verdade

Este documento é a fonte de verdade para o **modelo e as garantias de gravação do SSOT**. A implementação física deve obedecer rigorosamente às garantias e invariantes aqui estabelecidas.
