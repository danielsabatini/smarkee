# Resource Control Loop

> **Vigência (decisão [`0096`](../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md)):** `ipm/organization`, `ipm/serviceaccount` e `ipm/user` não têm mais Observer, Reconciler e Executor: um único processo `controller` observa, decide, age e reobserva numa transação, e os Streams `OBSERVED`, `ACTION` e `RESULT` e a tabela `<tipo>_action_result` não existem para eles. A função `decide(desired, observed)` é a mesma. Este documento descreve o modelo com os três papéis, que segue valendo para os demais tipos até a etapa S6 do plano de evolução, que o reescreve.

# 1. Introdução

O **Resource Control Loop** é o padrão arquitetural utilizado pela plataforma para gerenciar recursos de forma declarativa, assíncrona, idempotente e orientada à convergência.

O padrão define como a plataforma:

- recebe uma intenção;
- estabelece o estado desejado;
- observa a realidade;
- compara `desired` e `observed`;
- determina uma ação;
- executa a ação;
- observa novamente;
- atualiza o estado consolidado;
- converge continuamente para o estado desejado.

O padrão é independente da tecnologia utilizada para implementar a mensageria, persistência ou integração com sistemas externos.

Na implementação atual, NATS JetStream é utilizado como mecanismo de mensageria e PostgreSQL como SSOT, mas esses componentes são detalhes de implementação. O modelo e as garantias de gravação do SSOT estão em `SSOT.md`, e a implementação em PostgreSQL está em `POSTGRESQL.md`.

O Resource Control Loop é baseado no princípio:

```text
Desired → Observe → Reconcile → Act → Observe → Converge
```

# 2. Objetivo

Este documento define o padrão arquitetural oficial para componentes que gerenciam recursos da plataforma.

O objetivo é estabelecer uma estrutura consistente para recursos como:

```text
Organization
Agent
Runner
Tool
Identity
Vault
Project
Node
Volume
VM
...
```

O padrão deve permitir que diferentes recursos utilizem a mesma arquitetura conceitual sem que cada domínio crie um modelo próprio de controle.

# 3. Princípios

## 3.1 Declarativo sobre imperativo

O sistema deve representar **o estado que deseja alcançar**, e não uma sequência de comandos necessária para alcançá-lo.

```text
Desired
   │
   ▼
Reconciliation
   │
   ▼
Action
```

O `desired` não diz:

```text
"execute create now"
```

Ele diz:

```text
"este recurso deve existir"
```

O Reconciler determina como transformar a realidade atual na realidade desejada.

**Nota sobre `operation` no `desired`:** o `desired` é uma mensagem de estado e utiliza sempre a operação `changed` (`MESSAGING.md`). Ele não carrega verbo de ação: a decisão sobre `create`, `update` ou `delete` resulta exclusivamente da comparação entre `desired` e `observed`.

## 3.2 Desired e Observed são conceitos centrais

O controle é baseado em dois estados:

```text
Desired = o que queremos

Observed = o que existe
```

A decisão é:

```text
Desired
   vs
Observed
   ↓
Reconciliation
```

## 3.3 O Reconciler não executa

O Reconciler decide.

O Executor executa.

```text
Reconciler
    │
    │ Action
    ▼
Executor
```

O Reconciler não deve possuir credenciais ou lógica específica para alterar o sistema externo quando essa responsabilidade pertence ao Executor.

## 3.4 O Observer não corrige

O Observer observa.

Ele não deve alterar o sistema externo.

```text
Observer
   │
   │ read
   ▼
External System
```

A correção pertence ao Executor.

## 3.5 O Manager é a autoridade do recurso

O Manager é responsável pelo recurso no SSOT.

Responsabilidades principais:

- persistência;
- lifecycle;
- desired;
- generations;
- conditions;
- processamento das mensagens relevantes;
- publicação de eventos consolidados.

O Manager não deve assumir a responsabilidade de executar operações diretamente no sistema externo quando existe um Executor para essa finalidade.

## 3.6 Comunicação assíncrona

Os componentes não devem depender de chamadas síncronas entre si para executar o control loop.

Preferir:

```text
Component
    │
    ▼
 Messaging
    │
    ▼
Component
```

em vez de:

```text
Component A
    │ HTTP
    ▼
Component B
    │ HTTP
    ▼
Component C
```

## 3.7 Responsabilidade antes de processo

O padrão define **responsabilidades arquiteturais**: Receiver, Manager, Publisher, Observer, Reconciler e Executor. A publicação do outbox é do Publisher, o sexto papel (seção 6.6).

Na plataforma, cada papel de cada tipo de recurso é um **componente com processo e contêiner próprios**; a feature (módulo × tipo) é um projeto e uma imagem, com um entrypoint por papel (decisões 0015 e 0063). Os papéis não importam uns aos outros: usam só o `common/` da feature, e se comunicam pela mensageria, pelo SSOT (nos limites de cada papel) e por artefatos neutros de linguagem (*Componentes por papel*, seção 48).

Os critérios que justificam a separação são:

- possuem ciclos de escala diferentes;
- possuem permissões diferentes;
- possuem dependências diferentes;
- precisam de isolamento;
- possuem falhas independentes;
- possuem requisitos operacionais diferentes.

Esses critérios se aplicam a todos os papéis do loop, e por isso a separação é a regra. Um componente só é criado quando o seu papel passa a ser necessário (seção 48).

## 3.8 Estado do Reconciler

O Manager publica `desired`. O Observer publica `observed`. O Reconciler consome os dois, mais os resultados (`completed` e `failed`) das ações.

O estado do Reconciler é o último `desired` e o último `observed` de cada `resourceId`, obtidos **exclusivamente pela mensageria**. O Reconciler não acessa o SSOT.

```text
Manager  → desired  ┐
                    ├→ Reconciler (último desired + último observed por resourceId)
Observer → observed ┘
```

Regras:

- o transporte deve reter ao menos a última mensagem de `desired` e de `observed` por recurso (na implementação NATS, ver `NATS.md`);
- o estado mantido em memória é um cache descartável: após restart, **cada instância** do Reconciler o reconstrói a partir dessas mensagens retidas. O consumo é por instância, e não compartilhado, para que todas possuam o estado completo;
- o Reconciler não decide enquanto não possuir os dois estados, nem com `observed` inconclusivo ou desatualizado (ver *Observação inconclusiva*), nem com `desired` suspenso (ver *Fluxo de falha*);
- instâncias distintas podem tomar a mesma decisão. Isso é inofensivo porque a `action` possui `actionId` determinístico (ver *Identidade da Action*).

# 4. Modelo geral

O Resource Control Loop pode ser representado como:

```mermaid
flowchart LR
    D[Desired] --> R[Reconciler]
    O[Observed] --> R
    R --> A[Action]
    A --> E[Executor]
    E --> X[External System]
    X --> B[Observer]
    B --> O
```

O ponto fundamental é que:

```text
Desired
```

e:

```text
Observed
```

são **entradas independentes do Reconciler**.

Não existe uma cadeia obrigatória:

```text
Desired → Observer → Observed → Reconciler
```

Existe:

```text
             Desired
                │
                ▼
           ┌──────────┐
           │Reconciler│
           └─────┬────┘
                ▲
                │
             Observed
```

# 5. Arquitetura de referência

A arquitetura completa é:

```mermaid
flowchart TB

    Client[CLI / Client]
    Receiver[Receiver]

    subgraph Messaging[NATS / Messaging]
        Requested[requested]
        Desired[desired]
        Observed[observed]
        Action[action]
        Result[completed / failed]
        Updated[updated]
    end

    Manager[Manager<br/>SSOT + Lifecycle]
    Observer[Observer<br/>Reality]
    Reconciler[Reconciler<br/>Decision]
    Executor[Executor<br/>Execution]

    External[External System]

    Client -->|HTTP| Receiver
    Receiver -->|requested| Requested
    Requested --> Manager

    Manager -->|desired| Desired
    Desired --> Reconciler
    Desired --> Observer

    External -->|read| Observer
    Observer -->|observed| Observed
    Observed --> Reconciler
    Observed --> Manager

    Reconciler -->|action| Action
    Action --> Executor

    Executor -->|write| External
    Executor --> Result
    Result --> Manager
    Result --> Observer
    Result --> Reconciler

    Manager -->|updated| Updated
```

O Observer consome `desired` apenas para saber quais recursos observar. Ele não decide e não compara estados.

**Nota sobre os diagramas.** Neste documento, "o Manager publica `desired` e `updated`" significa que o **emissor** da mensagem é `manager`. Na implementação, o Manager grava a mensagem no outbox, na mesma transação do SSOT, e quem a publica no transporte é o Publisher (seção 6.6).

# 6. Componentes

# 6.1 Receiver

O Receiver é a porta de entrada do sistema: o componente que expõe a **API HTTP** do recurso (decisão 0020). Recebe os pedidos do cliente e atende as leituras.

Responsabilidades:

- autenticação;
- autorização;
- validação estrutural;
- geração de identificadores;
- criação de contexto de correlação;
- publicação de `requested`;
- consulta do SSOT;
- exposição do estado atual.

O Receiver não deve:

- possuir o SSOT;
- executar reconciliação;
- chamar diretamente o sistema externo;
- implementar lógica de integração com o provider.

Fluxo:

```mermaid
flowchart LR
    CLI[CLI] --> Receiver[Receiver]
    Receiver -->|requested| NATS[NATS]
    NATS --> Manager[Manager]
```

## 6.1.1 Interface HTTP

Cada tipo de recurso expõe a mesma interface, sob o prefixo do módulo e no plural do `resourceType` (`/v1/<módulo>/<tipos>`, por exemplo `/v1/ipm/organizations`; decisão 0030). As escritas são assíncronas: o Receiver publica `requested` e responde `202 Accepted` com o `operationId`, sem esperar o Manager. As leituras vêm das views versionadas do SSOT (`POSTGRESQL.md`, decisão 0004). Por isso, logo depois do `202` o recurso e a Operation ainda podem não existir no SSOT: a leitura responde `404` até o Manager gravá-los. O cliente que espera o resultado repete a leitura até o prazo (ou acompanha a Operation até `completed`), e não trata esse `404` inicial como recurso inexistente. Cada tipo implementa o subconjunto aplicável da interface: a Account, por exemplo, não tem `PATCH` nem listagem (decisão 0014).

| Método e rota | Efeito | Resposta |
|---|---|---|
| `POST /v1/<módulo>/<tipos>` | `requested` com operação `create`; o Receiver atribui o `resourceId` (UUIDv7) | `202` com `resourceId` e `operationId` |
| `GET /v1/<módulo>/<tipos>/{resourceId}` | leitura do recurso consolidado (`phase`, `conditions`, `resourceVersion`) | `200` ou `404` |
| `GET /v1/<módulo>/<tipos>?limit=&cursor=` | lista paginada por cursor opaco, ordenada por `resourceId`; `limit` padrão 50, máximo 200 | `200` com `items` e `nextCursor` (ausente na última página) |
| `PATCH /v1/<módulo>/<tipos>/{resourceId}` | `requested` com operação `update`; o corpo traz `resourceVersion` | `202` com `operationId` |
| `DELETE /v1/<módulo>/<tipos>/{resourceId}?resourceVersion=` | `requested` com operação `delete` (`lifecycle = absent`) | `202` com `operationId` |
| `GET /v1/<módulo>/<tipos>/{resourceId}/operations/{operationId}` | acompanhamento da Operation (estado e motivo de rejeição), aninhada ao recurso (decisão 0015) | `200` ou `404` |

Regras:

- **Idempotência do pedido:** o cabeçalho opcional `Idempotency-Key` nas escritas é a chave do cliente da qual o Receiver deriva o `operationId` (`SSOT.md`, decisão 0002). A chave não é armazenada nem transportada. Repetir a chave com o mesmo conteúdo devolve a Operation existente sem publicar de novo; com outro conteúdo, o Receiver responde `422`.
- **Concorrência otimista:** `update` e `delete` exigem o `resourceVersion` lido. O conflito é decidido pelo Manager e aparece como Operation `rejected` com motivo `conflict`. O Receiver pode antecipar um `409` quando a versão lida já difere, como conveniência.
- **Autorização:** o Receiver autoriza o solicitante antes de publicar e filtra as leituras pelas Organizations autorizadas (`RESOURCE-CONTROL-SECURITY.md`, *Isolamento entre organizations*).
- **Privilégios por campo:** o contrato do recurso pode restringir campos a operadores. Na Organization, o dono altera só o `name`; `platformAccess` e `reconciliation` exigem a role de operador do tipo, `ipm.organization.admin` (`403` caso contrário; padrão de nomes na decisão 0028).
- **Leitura da Operation:** só o solicitante (`requestedBy`) e os operadores (role `<módulo>.<tipo>.admin` do tipo) leem uma Operation. Uma Operation de solicitante `anonymous` não é legível por quem a criou (seção seguinte).
- **Erros:** `400` corpo inválido, `401` sem token válido, `403` sem permissão, `404` inexistente ou não autorizado, `409` conflito antecipado, `422` reuso da chave de idempotência, `429` limite de taxa, `503` `REQUESTED` cheio (rejeição repetível, `NATS.md`). Quando o contrato do recurso define regras de elegibilidade ou de cota, `403` leva um código estável no corpo (`api-error`): por exemplo, `EmailNotVerified` (e-mail do solicitante não verificado) e `QuotaExceeded` (cota de criação do dono excedida).

## 6.1.2 Escritas anônimas

Por padrão, toda escrita exige solicitante autenticado. A exceção deve estar declarada no contrato do recurso e registrada em decisão. Hoje existe uma só: o auto-cadastro de usuário (`POST /v1/core/accounts`, decisão 0014).

Uma escrita anônima:

- usa `requestedBy = anonymous` (um valor fixo, que não identifica a pessoa);
- tem **limite de taxa por origem** no gateway e no Receiver, com valores conservadores e configuráveis;
- tem **resposta uniforme**: o mesmo `202` e o mesmo corpo, exista ou não o recurso ou o dado informado (por exemplo, o e-mail). Não pode haver diferença observável de status, de corpo nem, de forma relevante, de tempo;
- **não permite acompanhar a Operation**: o cliente anônimo não consulta a Operation (`GET /v1/<módulo>/<tipos>/{resourceId}/operations/{operationId}`), e por isso não há `--wait`. Isso impede que a consulta revele se o dado já existia;
- aplica a validação estrita e os limites de tamanho do contrato (`SCHEMA.md`);
- não carrega segredo: a credencial é definida pelo próprio usuário no provedor de identidade, fora do loop.

# 6.2 Manager

O Manager é o **owner do recurso no SSOT**.

Responsabilidades:

```text
Resource
Desired
Observed
Lifecycle
Conditions
Generation
Operation
```

Fluxo:

```mermaid
flowchart LR
    Requested[requested] --> Manager

    Manager --> SSOT[(PostgreSQL)]

    Manager --> Desired[desired]

    Observed[observed] --> Manager
    Completed[completed] --> Manager

    Manager --> Updated[updated]
```

O Manager não precisa conhecer detalhes do provider.

Por exemplo, no caso de Organization, ele não precisa implementar chamadas para Zitadel.

# 6.3 Observer

O Observer transforma realidade externa em `observed`.

Responsabilidades:

- consultar sistemas externos;
- verificar existência;
- consultar configuração;
- coletar estado;
- produzir observações;
- detectar drift;
- executar observação periódica, independentemente de eventos, apenas para os recursos da sua partição (ver *Coordenação da observação*);
- observar o recurso após cada `completed` ou `failed`, com `causationId` igual ao `messageId` do resultado (ver *Observação inconclusiva*);
- informar `observedAt` e distinguir `present`, `absent` e `unknown` (ver *Observação inconclusiva*).

Fluxo:

```mermaid
flowchart LR
    External[External System]
    Observer[Observer]

    Observer -->|GET / Read| External
    External -->|Reality| Observer
    Observer -->|observed| NATS[NATS]
```

O Observer não deve:

```text
create
update
delete
```

diretamente no sistema externo.

# 6.4 Reconciler

O Reconciler é responsável exclusivamente pela **decisão de reconciliação**.

Ele consome:

```text
Desired
Observed
```

e produz:

```text
Action
```

Fluxo:

```mermaid
flowchart TB

    D[manager.desired]
    O[observer.observed]

    D --> R[Reconciler]
    O --> R

    R --> C{Desired == Observed?}

    C -->|Yes| N[No Action / noop]
    C -->|No| A[Action]
```

O Reconciler não deve:

- persistir o recurso como SSOT;
- chamar diretamente o provider;
- possuir lógica de Receiver;
- executar a ação.

# 6.5 Executor

O Executor transforma `Action` em uma operação no sistema externo.

Fluxo:

```mermaid
flowchart LR
    Action[reconciler.action] --> Executor
    Executor -->|Create / Update / Delete| External[External System]
    External --> Executor
    Executor -->|completed / failed| NATS[NATS]
```

O Executor é o componente que possui as credenciais necessárias para alterar o sistema externo.

Isso permite aplicar menor privilégio:

```text
Observer
    → read-only

Executor
    → write
```

Por possuir a credencial de escrita, o Executor é o último ponto de controle antes do sistema externo. Ele deve revalidar cada `action` contra o `desired` vigente antes de escrever (ver *Segurança do loop*).

# 6.6 Publicação do outbox (Publisher)

A publicação das mensagens que o Manager registrou no outbox do SSOT (`SSOT.md`, `POSTGRESQL.md`) é o papel do **Publisher** (decisão 0019). Ele existe porque o Manager grava o recurso e a mensagem a publicar na mesma transação (seção 8), e alguém precisa levar o outbox ao transporte.

## 6.6.1 O que é o outbox

O **outbox** (padrão *transactional outbox*) é uma tabela do SSOT que funciona como uma **caixa de saída**: cada linha é uma mensagem já pronta (`message_id`, `subject`, `payload`) que ainda precisa ir ao NATS. Ele resolve o problema da **escrita dupla**. Quando o Manager aplica um pedido, ele precisa fazer duas coisas: gravar o novo estado do recurso no banco **e** avisar os outros componentes pelo NATS. Banco e NATS são sistemas diferentes e não participam da mesma transação, então qualquer ordem falha em algum caso:

- gravar e depois publicar: se o processo cair entre os dois passos, o banco mudou, mas ninguém foi avisado (o recurso fica parado para sempre);
- publicar e depois gravar: se a gravação falhar, o NATS anunciou um estado que não existe.

Com o outbox, o Manager faz **uma única transação no banco**: grava o recurso, a Operation **e a linha do outbox**. Ou tudo é gravado, ou nada. Depois, e fora dessa transação, o Publisher lê as linhas pendentes, publica no NATS e só então marca `published_at`.

```text
Manager (uma transação):   BEGIN
                             atualiza o recurso        ← o estado
                             grava a Operation
                             grava a linha no outbox   ← "avisar que o desired mudou"
                           COMMIT                       (tudo ou nada)

Publisher (depois):        lê as linhas com published_at nulo, em ordem
                           publica no NATS e espera a confirmação
                           marca published_at           (só depois da confirmação)
```

Consequências: uma mensagem nunca se perde (a linha continua pendente até a confirmação); nunca se anuncia um estado que não foi gravado; e, se o Publisher cair entre publicar e marcar, a mensagem é publicada de novo (entrega *pelo menos uma vez*), o que os consumidores toleram por serem idempotentes e porque o NATS deduplica pelo `messageId`. O atraso do outbox (idade da linha pendente mais antiga) é o sinal de que a publicação está presa.

## 6.6.2 Quem decide e quem entrega

Há duas perguntas diferentes sobre uma mensagem `desired` ou `updated`, e cada papel responde uma:

| Pergunta | Papel | Como aparece |
|---|---|---|
| **Quem decidiu** que essa mensagem deve existir (qual foi a mudança, qual a geração, qual o conteúdo)? | **Manager** | É o `emitter` (`manager`), o primeiro token do Subject |
| **Quem entregou** a mensagem ao transporte? | **Publisher** | Está no campo `publishedBy` do envelope (`<módulo>-<tipo>-publisher`) e, de forma independente, na identidade de mensageria que publica (permissões e log do NATS) |

O `emitter` identifica o autor da decisão, e não o processo que a transportou (`MESSAGING.md` §6.1). Por isso o Subject `manager.desired.<módulo>.<tipo>.<id>.changed` não muda se o Publisher for trocado por outro mecanismo de entrega: os consumidores dependem de **quem decidiu**, e não de **como a mensagem chegou**. Cada papel responde só pelo que lhe cabe:

- o **Manager** responde pela decisão e pela gravação: valida, aplica, grava e registra no outbox. Não tem credencial para publicar no NATS;
- o **Publisher** responde pela entrega: ordem, confirmação, repetição e visibilidade do bloqueio. Não decide nem altera o conteúdo (apenas preenche `publishedAt` no instante da entrega) e só pode publicar os Subjects `manager.desired.<m>.<t>.>` e `manager.updated.<m>.<t>.>` do seu tipo. Ele preenche `publishedAt` e `publishedBy` no instante da entrega; `emitter` e o resto do conteúdo vêm do Manager e não são alterados.

O Publisher é um papel próprio da feature, com contêiner e *deployment* próprios (a imagem é a da feature, decisão 0063) e com papel de banco e identidade de mensageria próprios, para manter o menor privilégio:

- o **Manager** só **insere** no outbox; consome `requested`, `observed` e `completed`/`failed`;
- o **Publisher** só **lê** o outbox e atualiza `published_at`; entrega a mensagem no Subject do emissor `manager` (o autor da decisão; veja 6.6.2), em ordem por recurso, com uma instância ativa por outbox (trava consultiva de sessão), e só marca a publicação depois da confirmação do transporte.

O outbox é o contrato entre o Manager e o Publisher. O Publisher **não executa regra de negócio**.

# 7. O fluxo completo

O fluxo completo é dividido em seis fases encadeadas assincronamente por mensageria:

1. **Request (Entrada):** O cliente submete a intenção ao Receiver via HTTP (`POST`, `PATCH`, `DELETE`). O Receiver valida a estrutura, correlaciona a requisição e emite `requested`, respondendo rapidamente com `202 Accepted` acompanhado do `operationId`.
2. **Desired (Intenção declarativa):** O Manager consome `requested`, valida regras de negócio e cota, grava o recurso e a Operation no SSOT e registra a mensagem `desired` no outbox na mesma transação. O Publisher a despacha com operação `changed`, expressando a intenção de existência (`lifecycle = present | absent`).
3. **Observation (Leitura da realidade):** O Observer consulta o estado real no sistema externo com credencial restrita de leitura (`READ`) e publica `observed` contendo o resultado da presença (`presence: present | absent | unknown`) e o instante `observedAt`.
4. **Reconciliation (Decisão):** O Reconciler consome o último `desired` e o último `observed` retidos na mensageria. Compara os campos gerenciados: se houver divergência, decide a ação (`create`, `update`, `delete`); se convergido, emite `noop` (sem ação).
5. **Action (Despacho):** O Reconciler emite a mensagem `action` com um identificador determinístico (`actionId`) derivado do `resourceId`, da `desiredGeneration`, da operação e do `messageId` da observação que motivou a decisão.
6. **Execution (Aplicação externa):** O Executor consome `action`, consulta desfechos anteriores para deduplicação, aplica a operação no sistema externo com credencial de escrita (`WRITE`) e publica o resultado no barramento (`completed` ou `failed`).

O ciclo se completa com a **re-observação causal** disparada pelo resultado da execução: o Observer lê o sistema externo com `causationId` apontando para o resultado, e o Manager consome essa observação conclusiva para atualizar o SSOT, confirmar a geração (`observedGeneration = desiredGeneration`), concluir a Operation (`completed`) e publicar `updated`.

Visualmente:

```mermaid
flowchart LR

    A[1. Request]
    B[2. Desired]
    C[3. Observed]
    D[4. Reconcile]
    E[5. Action]
    F[6. Execute]
    G[External System]

    A --> B
    B --> D
    C --> D
    D --> E
    E --> F
    F --> G
    G --> C
```

# 8. Fase 1 — Request

O cliente solicita uma alteração.

Exemplo:

```text
sk ipm organization create --name acme
```

Fluxo:

```mermaid
sequenceDiagram
    participant CLI
    participant Receiver
    participant NATS
    participant Manager

    CLI->>Receiver: POST /v1/ipm/organizations
    Receiver->>NATS: receiver.requested.ipm.organization.<id>.create
    NATS->>Manager: requested
    Manager->>Manager: validate + persist
    Manager->>NATS: manager.desired.ipm.organization.<id>.changed
```

O Receiver retorna rapidamente:

```text
202 Accepted
```

O processamento continua de forma assíncrona.

Requisitos:

- o Receiver aceita uma chave de idempotência no `POST`: a repetição do mesmo pedido não cria outro recurso nem outro `desired`;
- atualizações devem informar a versão do recurso (`resourceVersion`, ver `MESSAGING.md`); uma versão desatualizada é rejeitada, e a atualização não sobrescreve silenciosamente outra concorrente;
- o Manager persiste o recurso e registra a publicação de `desired` na mesma transação (outbox, ver `SSOT.md` e `MESSAGING.md`), evitando o estado `persistido, mas não publicado`. A idempotência de entrada do Manager é semântica (chave de idempotência, monotonia de `observedAt` e `actionId`), e não depende de lembrar mensagens já vistas (`SSOT.md`).

# 9. Fase 2 — Desired

O Manager estabelece o estado desejado no SSOT.

Exemplo:

```json
{
  "resourceId": "organization-01",
  "desiredGeneration": 1,
  "desired": {
    "lifecycle": "present",
    "resourceName": "acme"
  }
}
```

Publicação:

```text
manager.desired.ipm.organization.organization-01.changed
```

O Desired é uma declaração.

Não significa que a Organization já existe.

```text
Desired = intenção
```

# 10. Fase 3 — Observation

O Observer consulta o sistema externo.

```mermaid
sequenceDiagram
    participant NATS
    participant Observer
    participant Zitadel

    NATS->>Observer: manager.desired...
    Observer->>Zitadel: GET organization
    Zitadel-->>Observer: 404 Not Found
    Observer->>NATS: observer.observed...changed (presence=absent)
```

O resultado é:

```text
Observed = absent
```

## 10.1 Observação inconclusiva

Uma observação possui três resultados:

| Resultado | Significado |
|---|---|
| `present` | O recurso foi lido e existe. |
| `absent` | O provider confirmou, de forma inequívoca, que o recurso não existe. |
| `unknown` | A leitura falhou ou foi inconclusiva. |

Erro de leitura (timeout, 5xx, 401/403, limite de taxa) é `unknown`, nunca `absent`. Somente a confirmação inequívoca de ausência é `absent`.

Toda observação informa o resultado no campo `presence` e o momento em `observedAt` (`MESSAGING.md`). O Reconciler:

- não emite `Action` com base em `unknown`;
- não emite `Action` com base em observação mais antiga que o limite de validade definido pelo domínio (mais estrito para ações destrutivas);
- aguarda nova observação quando a atual for inconclusiva ou desatualizada;
- após `completed` ou `failed`, não decide uma nova ação para o recurso enquanto não receber a observação causada por esse resultado (ver abaixo).

Os prazos do loop são parâmetros do contrato do recurso (`SCHEMA.md`): `observationInterval` (período da observação periódica), `observationValidity` (limite de validade do `observed`), `actionDeadline` (prazo de uma `action` pendente), `failureLimit` (falhas por geração) e `progressDeadline` (prazo para a geração convergir, decisão 0078).

### Ação sem efeito e prazo de progresso (decisão 0078)

Uma `action` que termina `completed` sem que a observação causada por ela convergir é uma **ação sem efeito** (por exemplo, quando o Executor e o Observer rodam com configurações diferentes). O Reconciler a conta e aplica a ela o mesmo backoff exponencial das falhas, com um aviso (`action had no effect`) que traz os nomes dos campos divergentes. Assim uma ação que não muda nada não se repete sem freio.

O Manager mantém a condition `Progressing`, como a do Deployment do Kubernetes: `True` (`Reconciling`) desde a primeira observação da geração atual que não converge, `True` (`Converged`) quando converge, e `False` (`ProgressDeadlineExceeded`) quando o `progressDeadline` passa sem convergir. Nesse caso a fase vai para `Failed` e sai um aviso (`progress deadline exceeded`). O loop não é suspenso: segue tentando, no ritmo do backoff, e volta a `Ready` sozinho se a causa sumir.

### Ordenação causal após uma ação

Depois de `completed` ou `failed` de uma `action`, o Observer faz uma observação cujo `causationId` é o `messageId` desse resultado. O Reconciler só volta a decidir sobre o recurso quando recebe essa observação. Observações periódicas posteriores são admitidas depois dela.

Isso evita decidir com uma leitura anterior à execução sem depender de relógios sincronizados entre serviços.

Se a observação causada não chegar dentro do prazo definido pelo domínio (por exemplo, o Observer da partição está indisponível), o Manager registra a condition `ObservationStale`, e o Reconciler volta a aceitar a próxima observação conclusiva. O mesmo ocorre quando o recurso permanece `unknown` por mais que o prazo.

Implementação (decisão 0090): o prazo é o `progressDeadline`, contado desde a primeira `unknown` da sequência. Esgotado, `ObservationStale` fica `True` (`Timeout`) e um recurso com trabalho pendente (`Pending`, `Reconciling` ou `Deleting`) vai para `Failed`, sem suspender o loop. Uma observação conclusiva encerra a sequência e o recurso converge sozinho. Em ambos os prazos (progresso e observação) as Operations abertas da geração atual terminam `failed`.

# 11. Fase 4 — Reconciliation

O Reconciler recebe os dois estados.

```mermaid
flowchart TB

    D["manager.desired<br/>lifecycle = present"]
    O["observer.observed<br/>lifecycle = absent"]

    D --> R["Reconciler"]

    O --> R

    R --> C{"Compare"}

    C -->|"Different"| A["action.create"]
```

A decisão:

```text
Desired = present
Observed = absent

→ create
```

Publicação:

```text
reconciler.action.ipm.organization.<id>.create
```

# 12. Gatilhos da reconciliação

`desired` e `observed` são **entradas independentes** do Reconciler. Esta é uma propriedade fundamental do padrão.

O Reconciler pode ser acionado por:

| Gatilho | Exemplo |
|---|---|
| `desired` mudou | O Manager publica uma nova geração. O Reconciler usa o último `observed` retido, desde que seja conclusivo e esteja dentro do limite de validade, sem esperar nova mensagem. |
| `observed` mudou | Um administrador altera o sistema externo. O Observer publica a nova realidade, e o Reconciler detecta o **drift**. |
| Resultado de uma `action` | `completed` ou `failed` libera nova decisão, após a observação causada (ver *Observação inconclusiva*). |
| Reconciliação periódica | Recuperação de perda de mensagem, restart ou inconsistência transitória (ver *Reconciliation periódica*). |
| Retry / recovery | Nova tentativa após falha transitória, sob backoff. |

O estado utilizado é o descrito em *Estado do Reconciler*.

# 13. Drift

Drift ocorre quando:

```text
Desired != Observed
```

Exemplo:

Outro exemplo:

O Reconciler não precisa saber quem causou o drift.

Ele apenas responde:

```text
Desired != Observed
```

O drift pode ter sido causado por:

- alteração manual;
- alteração por outro sistema;
- falha parcial;
- mudança externa;
- perda de estado;
- operação concorrente.

O mecanismo de correção permanece o mesmo. Quando o drift se repete continuamente, aplicam-se as proteções descritas em *Proteções de carga e estabilidade*.

# 14. Fase 5 — Action

A Action representa uma decisão.

Exemplo:

```text
reconciler.action.ipm.organization.<id>.create
```

Payload:

```json
{
  "messageType": "action",
  "operation": "create",
  "actionId": "organization-01.1.create.obs-7f3a",
  "resourceId": "organization-01",
  "desiredGeneration": 1,
  "data": {
    "reason": "resourceNotFound"
  }
}
```

A Action não é o Desired.

```text
Desired
   ↓
"o que deve existir"

Action
   ↓
"o que precisa ser feito agora"
```

## 14.1 Identidade da Action

O `actionId` é **determinístico**: derivado de `resourceId`, `desiredGeneration`, `operation` e da **observação que motivou a decisão** (o `messageId` do `observed` conclusivo utilizado).

- A mesma decisão sobre o mesmo estado e a mesma observação produz o mesmo `actionId`, o que permite deduplicar.
- Uma nova observação produz um novo `actionId`, mesmo com a mesma geração e a mesma operação. Isso é necessário: se o recurso externo for removido depois de uma criação bem-sucedida, a nova decisão de `create` deve ser executada, e não descartada como duplicata.
- A deduplicação ocorre em três pontos: o publicador usa o `actionId` como chave de deduplicação do transporte (quando suportado), o Reconciler não reemite enquanto houver `action` pendente e o Executor consulta o desfecho já registrado (ver *Desfecho e deduplicação no Executor*). A deduplicação do Executor é obrigatória e não depende do transporte.
- O Reconciler não reemite uma `action` enquanto houver outra pendente para o recurso (sem `completed` ou `failed` correspondente). Ao expirar o prazo de ação definido pelo domínio, ele pode reemitir com o mesmo `actionId`.
- Instâncias do Reconciler com observações diferentes (corrida) podem gerar `actionId` diferentes para o mesmo recurso. O Executor as serializa e, por ser idempotente, a segunda não produz efeito adicional.
- Uma `action` baseada em geração obsoleta é descartada pelo Executor.

O campo é definido em `MESSAGING.md` (envelope).

# 15. Fase 6 — Execution

O Executor consome a Action.

```mermaid
sequenceDiagram
    participant Reconciler
    participant NATS
    participant Executor
    participant External

    Reconciler->>NATS: action.create
    NATS->>Executor: action.create
    Executor->>External: Create
    External-->>Executor: Success
    Executor->>NATS: completed.create
```

O Executor não decide se a ação é necessária.

Essa decisão pertence ao Reconciler.

## 15.1 Desfecho e deduplicação no Executor

Antes de executar, o Executor consulta o desfecho já registrado para o `actionId`, ou seja, o último `completed` ou `failed` publicado por ele para o recurso e a operação (lido do transporte, em modo somente leitura):

| Desfecho registrado | Comportamento |
|---|---|
| Nenhum | Executa. Isso inclui a execução interrompida por falha: a repetição é segura pela chave de correlação com o recurso externo (ver *Reconciliation é idempotente*). |
| `completed` | Não executa. Confirma a mensagem e republica o `completed` (idempotente). |
| `failed` permanente | Não executa. Republica o `failed`. |

O registro dura o tempo de retenção dos resultados no transporte. Passado esse prazo, a proteção contra execução repetida é a idempotência do próprio Executor.

Uma reemissão com o mesmo `actionId` só repete a execução quando não houver desfecho registrado.

# 16. Completed não significa convergência

Este princípio é obrigatório.

```text
executor.completed
        ≠
resource converged
```

`completed` significa:

> A operação solicitada foi executada com sucesso.

A convergência somente pode ser confirmada pela observação compatível.

# 17. Nova observação

Após a execução, o Observer verifica novamente, com `causationId` igual ao `messageId` do resultado. Se o recurso existe, publica `observed` com `presence=present`. Agora:

```text
Desired = present
Observed = present
```

# 18. Convergência

O Reconciler compara novamente:

Resultado:

```text
No Action
```

O recurso convergiu.

## 18.1 Comparação entre Desired e Observed

A pergunta "Desired == Observed?" deve ter definição explícita para cada recurso:

- **campos gerenciados:** apenas os campos declarados em `desired` participam da comparação; campos não declarados não geram drift;
- **normalização:** os valores são normalizados antes da comparação (caixa, ordenação de listas, formatação), conforme o contrato do recurso;
- **defaults do provider:** valores preenchidos pelo provider e não declarados em `desired` não constituem drift;
- **resultado:** iguais → `noop`; diferentes → `Action` determinada pela diferença.

Uma comparação mal definida produz `update` infinito. A definição é declarada por anotação nos campos do contrato do recurso (`managed`, `normalization` e `providerDefault`; ver `SCHEMA.md`).

# 19. Atualização do SSOT

O Manager recebe a observação e atualiza o Resource.

Exemplo:

```text
phase = Ready
desiredGeneration = 1
observedGeneration = 1
condition = Ready=True (observedGeneration = 1)
```

O Manager só confirma a geração (`observedGeneration`) com uma observação feita depois dela (seção 36).

# 20. Fluxo completo da Organization

```mermaid
sequenceDiagram

    participant CLI
    participant Receiver
    participant NATS
    participant Manager
    participant Observer
    participant Reconciler
    participant Executor
    participant Zitadel

    CLI->>Receiver: POST /v1/ipm/organizations
    Receiver->>NATS: requested.create

    NATS->>Manager: requested.create
    Manager->>Manager: validate
    Manager->>Manager: persist Resource
    Manager->>NATS: desired.changed

    NATS->>Observer: desired.changed
    Observer->>Zitadel: GET organization
    Zitadel-->>Observer: 404
    Observer->>NATS: observed presence=absent

    NATS->>Reconciler: desired.changed
    NATS->>Reconciler: observed presence=absent

    Reconciler->>Reconciler: compare
    Reconciler->>NATS: action.create

    NATS->>Executor: action.create
    Executor->>Zitadel: POST organization
    Zitadel-->>Executor: 201 Created
    Executor->>NATS: completed.create

    NATS->>Observer: trigger observation
    Observer->>Zitadel: GET organization
    Zitadel-->>Observer: 200 OK
    Observer->>NATS: observed presence=present

    NATS->>Manager: observed presence=present
    Manager->>Manager: update SSOT
    Manager->>NATS: updated.changed

    CLI->>Receiver: GET /v1/ipm/organizations/<id>
    Receiver-->>CLI: phase=Ready
```

# 21. Fluxo de atualização

Uma alteração do `desired` incrementa `desiredGeneration`. O Reconciler compara o novo `desired` com o último `observed`, que ainda reflete a geração anterior, e decide `update`. Após a execução, o Observer observa o novo conteúdo e o Reconciler confirma a convergência pela comparação de conteúdo (ver *Comparação entre Desired e Observed*).

**Toda alteração percorre o mesmo caminho** (decisão 0072), inclusive a de um campo da plataforma que o provedor não tem (`x-managed: false`): nova geração, fase `Reconciling`, Operation `accepted` e `desired` no outbox. O Reconciler decide `update` se houver divergência em campo gerenciado, ou não faz nada se não houver. Nos dois casos, a Operation conclui quando a observação da nova geração a confirma (seção 36), e o Manager publica o `updated`. Não existe uma alteração que conclua sem passar pelo loop. Um controle da plataforma que precise aparecer no provedor vira campo gerenciado e é gravado como metadado (por exemplo, `deletionProtection`, decisão 0074).

# 22. Fluxo de remoção

A remoção também é declarativa: o `desired` passa a `lifecycle = absent`. O Reconciler decide `delete` enquanto o `observed` indicar `present`, e converge quando a observação indicar `absent`.

A plataforma não precisa representar a exclusão como um comando imperativo no `desired`.

Após a convergência da remoção, o Manager remove o recurso do SSOT. O último `desired` (`lifecycle=absent`) permanece no transporte como tombstone até uma limpeza administrativa; Reconciler e Observer ignoram recurso com `lifecycle=absent` já convergido (`NATS.md` e `RESOURCE-CONTROL-SECURITY.md`).

**Limitação conhecida:** este padrão não define a ordem de remoção entre recursos dependentes (por exemplo, uma Organization com Agents). Enquanto não houver regra própria, a remoção de um recurso com dependentes deve ser tratada pelo domínio.

# 23. Fluxo de falha

```mermaid
flowchart TB

    Action["Action"]
    Executor["Executor"]
    External["External System"]

    Action --> Executor
    Executor --> External

    External -->|failure| Retry["Retry"]

    Retry -->|temporary| Executor
    Retry -->|permanent| Failed["Failed"]

    Failed --> Condition["Condition / Error"]
```

Uma falha de execução não deve destruir o Desired. O Desired permanece como fonte da intenção, o que permite retry e recuperação.

Retry, backoff, limite de tentativas e quarentena de mensagens seguem `NATS.md`. No nível do recurso:

- falha transitória mantém o recurso em `Reconciling`. O backoff entre tentativas é aplicado pelo Reconciler a partir do último `failed` do recurso, que o transporte retém;
- o Manager, dono do lifecycle, conta as falhas por geração a partir dos `failed` que consome. Ao atingir o `failureLimit`, marca o recurso como `Failed` e registra a causa em `conditions`;
- ao marcar `Failed`, o Manager republica o `desired` com a reconciliação **suspensa** (campo `reconciliation` do `desired`, ver `SCHEMA.md`). O Reconciler não decide enquanto o `desired` estiver suspenso, o que impede o ciclo contínuo contra o provider;
- a suspensão termina por nova geração de `desired` ou por intervenção explícita, em que o Manager republica o `desired` com a reconciliação ativa.

# 24. Falha após alteração externa

Este é um dos cenários mais importantes.

```mermaid
sequenceDiagram

    participant R as Reconciler
    participant E as Executor
    participant X as External
    participant O as Observer

    R->>E: action.create
    E->>X: create
    X-->>E: success

    Note over E: processo falha antes de publicar completed

    O->>X: GET
    X-->>O: resource exists
    O->>R: observed presence=present

    R->>R: compare Desired vs Observed
    R-->>R: converged
```

A arquitetura não depende de `completed` para recuperar o estado.

A realidade observada é a fonte de evidência.

# 25. Reconciliation periódica

Eventos não devem ser a única forma de disparar reconciliação.

O sistema deve possuir reconciliação periódica:

Isso permite recuperação após:

- perda de mensagem;
- indisponibilidade temporária;
- restart;
- falha do consumidor;
- falha externa;
- inconsistência transitória.

O período deve ser definido de acordo com o domínio.

Requisitos:

- o Observer observa periodicamente, para que `observed` não envelheça indefinidamente;
- o Reconciler reavalia periodicamente o estado que possui;
- os disparos periódicos usam jitter, para evitar rajadas sincronizadas.

# 26. Reconciliation é idempotente

Uma mesma mensagem pode provocar múltiplas reconciliações: `desired` duplicado, `observed` repetido ou decisões simultâneas de instâncias diferentes. O resultado deve ser o mesmo, sem efeito colateral indevido.

O Executor também deve ser idempotente ou utilizar mecanismos que tornem a operação segura.

Para que a repetição de um `create` (por exemplo, após timeout) não duplique o recurso, o Executor deve possuir uma chave de correlação com o recurso externo: um identificador externo determinístico, uma chave de idempotência aceita pelo provider ou uma consulta prévia quando o provider não garante unicidade.

# 26.1 Coordenação da observação

Cada instância do Reconciler e do Observer mantém o estado completo (ver *Estado do Reconciler*). Se todas as instâncias do Observer observassem todos os recursos, o provider receberia N vezes as leituras.

Por isso, a observação periódica de um recurso é feita por **uma instância por vez**. O mecanismo padrão é a **partição determinística por `resourceId`**: cada instância observa os recursos em que `hash(resourceId) mod número de réplicas` é igual ao índice estável da sua réplica.

- a indisponibilidade de uma instância deixa a sua partição sem observação até que ela retorne. O `observedAt` envelhece, o Reconciler não decide (ver *Observação inconclusiva*) e a condition `ObservationStale` sinaliza o problema;
- ao alterar o número de réplicas, a distribuição muda e alguns recursos podem ser observados por duas instâncias por um período. Observação é leitura, então o efeito é inofensivo;
- as decisões do Reconciler não precisam de partição, pois decisões duplicadas são deduplicadas por `actionId`. Se a carga exigir, a mesma regra pode ser aplicada ao Reconciler.

# 27. Idempotência em cada camada

Cada camada possui uma estratégia diferente. Não existe uma única técnica universal de idempotência.

| Camada | Estratégia |
|---|---|
| Receiver | Chave de idempotência no pedido |
| Manager | Constraints do recurso, `resourceVersion` e outbox |
| Reconciler | Comparação de conteúdo, geração e `actionId` |
| Executor | Desfecho por `actionId` e chave de correlação com o recurso externo |
| Provider | Semântica própria do provider |

# 28. Mensageria

A comunicação utiliza o modelo semântico definido em `MESSAGING.md`.

Formato:

```text
<emitter>.<messageType>.<module>.<resourceType>.<resourceId>.<operation>
```

Exemplos:

```text
receiver.requested.ipm.organization.<id>.create

manager.desired.ipm.organization.<id>.changed

observer.observed.ipm.organization.<id>.changed

reconciler.action.ipm.organization.<id>.create

executor.completed.ipm.organization.<id>.create

manager.updated.ipm.organization.<id>.changed
```

O resultado da observação (`present`, `absent` ou `unknown`) é informado no campo `presence`, e não no endereço. Cada `messageType` é persistido em seu próprio Stream, com a retenção da sua classe de mensagem (trabalho, estado ou fato), conforme `NATS.md`.

# 29. Quem publica e quem consome

O padrão define explicitamente:

| Mensagem | Publicador | Consumidores principais |
|---|---|---|
| `requested` | Receiver | Manager |
| `desired` | Manager | Reconciler, Observer, Executor (revalidação, somente leitura), outros interessados |
| `observed` | Observer | Reconciler, Manager, outros consumidores |
| `action` | Reconciler | Executor |
| `completed` | Executor | Manager, Observer (observação causada), Reconciler (rastreio de action pendente), Executor (desfecho, somente leitura), auditoria |
| `updated` | Manager | Console, auditoria, métricas, consumidores |
| `failed` | Executor/componente responsável | Manager (contagem de falhas), Observer (observação causada), Reconciler (backoff e action pendente), Executor (desfecho, somente leitura), observabilidade |

O consumidor não deve ser codificado no subject.

# 30. Matriz de responsabilidades

| Responsabilidade | Receiver | Manager | Observer | Reconciler | Executor |
|---|---:|---:|---:|---:|---:|
| AuthN | ✓ | | | | |
| Schema validation | ✓ | ✓ | | | |
| Business validation | | ✓ | | | |
| SSOT | | ✓ | | | |
| Desired | | ✓ | | | |
| Observe external | | | ✓ | | |
| Observed | | | ✓ | | |
| Compare Desired/Observed | | | | ✓ | |
| Decide Action | | | | ✓ | |
| Execute Action | | | | | ✓ |
| External write | | | | | ✓ |
| Lifecycle | | ✓ | | | |
| Conditions | | ✓ | | | |
| Provider credentials | | | Read | | Write |

# 31. Separação de privilégios

A arquitetura permite aplicar princípio de menor privilégio.

```mermaid
flowchart LR

    Observer["Observer<br/>READ"]
    Executor["Executor<br/>WRITE"]

    Observer -->|"GET / LIST"| External["External System"]

    Executor -->|"POST / PATCH / DELETE"| External
```

Credenciais de escrita não devem estar disponíveis para:

```text
Receiver
Manager
Observer
Reconciler
```

quando não forem necessárias.

Cada serviço (módulo, tipo de recurso e papel) deve possuir identidade própria no barramento, com permissões restritas ao seu papel e ao seu tipo de recurso. Os requisitos completos estão em `RESOURCE-CONTROL-SECURITY.md`.

# 32. Separação de falhas

Cada componente possui um domínio de falha diferente:

| Componente | Falha |
|---|---|
| Receiver | Indisponibilidade de entrada de pedidos |
| Manager | Falha de persistência: não aceita novos pedidos nem atualiza o SSOT |
| Observer | Falha de leitura do provider: `observed` envelhece (`unknown`) |
| Reconciler | Falha de decisão: nenhuma nova `action` |
| Executor | Falha de escrita no provider: `failed` e retry |

O objetivo é permitir que uma falha em um componente não exija indisponibilidade de toda a plataforma.

# 33. Escalabilidade

Cada serviço escala conforme o seu papel. Nem toda réplica adicional aumenta a vazão:

| Serviço | Réplicas servem para | Como a carga é dividida |
|---|---|---|
| Receiver | Vazão e disponibilidade | Réplicas sem estado atrás do gateway; o limite de taxa do cadastro anônimo é em memória, por instância (o primeiro nível é o do gateway) |
| Manager | Vazão e disponibilidade | Réplicas compartilham `requested`, `observed` e `result`; o SSOT garante a idempotência |
| Publisher | Disponibilidade | Uma instância ativa por outbox (trava consultiva de sessão); as demais aguardam a trava |
| Observer | Vazão de observação e disponibilidade | Partição por `resourceId` (ver *Coordenação da observação*) |
| Reconciler | Disponibilidade | Cada réplica mantém o estado completo e toma decisões equivalentes. Se a CPU exigir, aplicar a partição por `resourceId` |
| Executor | Disponibilidade | Uma `action` por vez em cada recurso (*single-flight*), com paralelismo entre recursos por partição do Stream `ACTION` por `resourceId` (`docs/messaging/NATS.md` §7.5; decisão 0018). A vazão total é limitada pelo provider |

# 34. Concorrência

A unidade natural de concorrência é o recurso: a reconciliação de recursos distintos é independente.

Quando houver necessidade de serialização, ela deve ser definida explicitamente por `resourceId` ou `orderingKey`. Não assumir ordenação global.

Para cada `resourceId`, apenas uma `action` deve estar em execução por vez (*single-flight*). Várias instâncias do Reconciler podem decidir o mesmo recurso; a serialização é responsabilidade do **Executor**, e não do Reconciler. O Executor deve garantir uma única execução por vez por recurso (por exemplo, consumindo uma `action` por vez em cada partição do `resourceId`, decisão 0018) e permanecer idempotente, pois sob falha uma `action` pode ser entregue a outra instância enquanto a anterior ainda executa (`NATS.md`).

# 35. DesiredGeneration

A geração identifica uma versão lógica do estado desejado.

Exemplo:

```text
generation 1
    name = ACME

generation 2
    name = ACME Corp

generation 3
    name = ACME Corporation
```

O Reconciler deve evitar aplicar uma decisão baseada em uma geração antiga quando uma geração mais recente já estiver disponível.

# 36. ObservedGeneration

O modelo é o do Kubernetes (`metadata.generation` e `status.observedGeneration`; decisões 0071 e 0072). `observedGeneration` é a **última geração cuja convergência o Manager confirmou**. "Terminou" significa `observedGeneration == desiredGeneration` com `phase = Ready`.

O sistema externo não conhece a geração do `desired`. Por isso, a confirmação depende de duas condições, conferidas pelo Manager na unidade atômica do `observed`:

1. **conteúdo:** a comparação entre `desired` e `observed` converge (ver *Comparação entre Desired e Observed*);
2. **tempo causal:** a observação foi feita **depois** da geração. O Observer informa no `observedGeneration` do envelope `observed` a geração que conhecia **antes** de ler o provedor. Um `desired` que chegue durante a leitura não é atribuído a ela.

Uma leitura anterior à geração não a confirma, mesmo com o conteúdo igual. É o que acontece numa alteração só em campo da plataforma (`x-managed: false`), que o provedor não tem: o Reconciler não encontra o que fazer (noop), e quem conclui é a observação da nova geração.

Regras:

- `observedGeneration` só cresce e nunca passa de `desiredGeneration` (restrição no banco);
- o Manager grava o par na mesma unidade atômica do estado e o publica no `updated` (`desiredGeneration` e `observedGeneration`), para que Console, CLI e outros consumidores saibam qual geração terminou;
- a Operation de uma geração conclui quando essa geração é confirmada.

A geração também serve para:

- descartar uma `action` baseada em geração obsoleta;
- identificar a que geração uma condition se refere.

Quando o provider permite gravar a geração no próprio recurso externo (por exemplo, como metadado gravado pelo Executor), ela pode ser lida pelo Observer como evidência adicional:

```text
Desired:
generation = 5

Recurso externo (metadado gravado pelo Executor):
generation = 4
```

Isso indica que o recurso externo ainda não reflete a geração 5.

# 37. Lifecycle

O lifecycle do Resource Control Loop é definido no recurso, não na mensageria. A fase consolidada é o campo `phase`, mantido pelo Manager; ela não se confunde com `lifecycle` em `desired` (intenção de existência: `present` ou `absent`) nem com `presence` em `observed` (`SCHEMA.md`).

Exemplo:

```mermaid
stateDiagram-v2

    [*] --> Pending
    Pending --> Reconciling: Início da reconciliação
    Reconciling --> Ready: Convergência observada
    Reconciling --> Failed: failureLimit ou progressDeadline excedido
    Ready --> Reconciling: Alteração de desired ou drift externo
    Ready --> Deleting: Pedido de remoção (lifecycle=absent)
    Failed --> Reconciling: Nova geração ou reativação
    Deleting --> [*]: Confirmação de ausência (presence=absent)
```

## 37.1 Fases consolidadas do recurso (`phase`)

| Fase (`phase`) | Significado | Como entra | Como sai |
|---|---|---|---|
| **`Pending`** | Recurso registrado no SSOT, aguardando o início do processamento do loop. | Gravação inicial do recurso pelo Manager ao aceitar um pedido de criação (`requested`). | Transiciona para `Reconciling` assim que a reconciliação do recurso é iniciada. |
| **`Reconciling`** | O recurso está ativamente convergindo para o estado desejado (processando ações, aguardando execução ou em backoff). Um recurso pode permanecer em `Reconciling` por múltiplos ciclos normais. | Entrada a partir de `Pending`, criação de nova geração (`desiredGeneration`), ou detecção de drift pelo Observer. | Transiciona para `Ready` quando o conteúdo observado for idêntico ao desejado em observação causal; ou para `Failed` se esgotar o limite de falhas ou o prazo de progresso. |
| **`Ready`** | O estado desejado foi plenamente alcançado e confirmado pelo sistema externo (`observedGeneration == desiredGeneration`). | Quando a observação causal confirma que todos os campos gerenciados divergentes convergiram. | Volta para `Reconciling` se o `desired` mudar ou se o Observer detectar drift externo; transiciona para `Deleting` se a remoção for solicitada. |
| **`Failed`** | O loop esgotou as tentativas automáticas e a reconciliação foi suspensa para evitar sobrecarga ou laço infinito contra o provedor. | Quando `failureCount` atinge o `failureLimit` do contrato, ou quando o `progressDeadline` expira sem convergência (decisão 0078). | Sai para `Reconciling` quando uma nova geração do `desired` é submetida (que zera as falhas e reativa a reconciliação) ou por intervenção explícita no SSOT. |
| **`Deleting`** | O recurso teve sua remoção declarada (`lifecycle = absent`) e aguarda a exclusão no sistema externo pelo Executor. | Solicitação de exclusão aceita no SSOT (com `deletionProtection = false`). | O registro é **fisicamente removido** do SSOT assim que o Observer confirma `presence = absent` (invariante 8 do SSOT: remoção física só após a convergência). |

## 37.2 Diferenciação entre os conceitos de Estado

Para evitar ambiguidade conceitual, a plataforma distingue explicitamente os papéis de cada campo de estado:

| Conceito | Campo | Onde reside | Valores possíveis | Papel no controle |
|---|---|---|---|---|
| **Fase consolidada** | `phase` | `Resource` (SSOT) | `Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting` | Visão oficial do ciclo de vida do recurso na plataforma. |
| **Intenção de existência** | `lifecycle` | `desired` (SSOT e NATS) | `present`, `absent` | Declara se o recurso deve existir ou ser destruído. |
| **Controle de reconciliação** | `reconciliation` | `desired` (SSOT e NATS) | `active`, `suspended` | Habilita ou suspende as tomadas de decisão pelo Reconciler. |
| **Proteção contra exclusão** | `deletionProtection` | `desired` (SSOT e NATS) | `true`, `false` | Impede recusa ou permite pedidos de remoção (`delete`). |
| **Presença real** | `presence` | `observed` (SSOT e NATS) | `present`, `absent`, `unknown` | O que foi constatado no provedor externo (`unknown` nunca é tratado como ausente). |
| **Estado da requisição** | `operationStatus` | `Operation` (SSOT) | `accepted`, `in_progress`, `completed`, `failed`, `rejected` | Acompanhamento do processamento da solicitação do cliente. |

# 38. Conditions

Conditions representam fatos consolidados sobre o recurso ao longo do tempo, seguindo o padrão estabelecido pelo Kubernetes (`type`, `status`, `reason`, `message`, `observedGeneration`, `lastTransitionAt`).

São calculadas e persistidas atomicamente no SSOT pelo **Manager** a cada observação ou resultado processado.

Exemplo:

```json
{
  "type": "Ready",
  "status": "True",
  "reason": "Reconciled",
  "message": "Organization exists in Zitadel",
  "observedGeneration": 1,
  "lastTransitionAt": "2026-10-04T00:00:00Z"
}
```

## 38.1 Tipos oficiais de Condition

Os contratos da plataforma definem o vocabulário padronizado de conditions:

| Condition (`type`) | Status (`status`) | Motivo típico (`reason`) | Significado |
|---|---|---|---|
| **`Ready`** | `True` | `Reconciled` | O recurso convergiu completamente e está pronto para uso. |
| | `False` | `Reconciling` | O recurso está em processo de convergência. |
| | `False` | `Failed` | Falha permanente ou esgotamento de retries na geração vigente. |
| **`Progressing`**<br/>*(decisão 0078)* | `True` | `Reconciling` | Há trabalho e progresso ativo sendo executado para a geração atual. |
| | `True` | `Converged` | O progresso da geração foi concluído com sucesso. |
| | `False` | `ProgressDeadlineExceeded` | O tempo decorrido desde o início da geração excedeu o `progressDeadline` (padrão de 5 minutos) sem convergir. |
| **`ObservationStale`**<br/>*(decisão 0090)* | `False` | `ObservationUnknown` | O recurso está `unknown` há menos que o prazo. |
| | `True` | `Timeout` | O provedor permaneceu em `unknown` por mais que o `progressDeadline`. |
| | `False` | `ObservationResumed` | Voltou uma observação conclusiva depois do `Timeout`. |
| **`DriftLoop`** | `True` | `RepeatedDrift` | Correções de drift estão ocorrendo ciclicamente em curto intervalo de tempo. |

# 39. Operation

Uma `Operation` acompanha o processamento assíncrono de uma solicitação submetida pelo cliente (`GET /v1/<módulo>/<tipos>/{resourceId}/operations/{operationId}`).

A Operation **não deve ser confundida com o Resource**:

```text
Resource  = objeto gerenciado permanente na plataforma (ex: Organization, User, Account)
Operation = ciclo de atendimento de uma requisição assíncrona sobre um recurso
```

A Operation é mantida pelo Manager no SSOT e exposta pelo Receiver; não trafega no envelope das mensagens, e o `correlationId` correlaciona a Operation às mensagens do fluxo. O `operationId` é gerado pelo Receiver e transportado no corpo do `requested`.

## 39.1 Estados da Operation (`operationStatus`)

| Status | Significado |
|---|---|
| **`accepted`** | O pedido foi recebido pelo Receiver, validado pelo Manager e registrado no SSOT com o `desired` enfileirado no outbox. |
| **`in_progress`** | A reconciliação da solicitação está em andamento no loop. |
| **`completed`** | A solicitação foi concluída com sucesso: o recurso convergiu e a geração requerida foi confirmada (`observedGeneration == desiredGeneration`). |
| **`failed`** | A solicitação não pôde ser atendida e a execução falhou permanentemente. |
| **`rejected`** | A requisição foi recusada pelo Manager antes de entrar no loop (o recurso não é alterado e nenhum `desired` é gerado). |

## 39.2 Motivos de Rejeição (`operationStatusReason`)

Presente exclusivamente quando `operationStatus = rejected`:

| Motivo (`operationStatusReason`) | Significado |
|---|---|
| **`conflict`** | Concorrência otimista: a `resourceVersion` informada pelo cliente no `PATCH`/`DELETE` está desatualizada em relação ao SSOT. |
| **`validation`** | Violação de regras de negócio ou de contrato (ex: nome já em uso, cota de recursos excedida, e-mail não verificado). |
| **`not_found`** | O recurso alvo da alteração ou remoção não existe no SSOT. |
| **`protected`** | O pedido de `DELETE` foi recusado porque o recurso possui a proteção contra exclusão ativa (`deletionProtection = true`, decisão 0043). |

# 40. CLI e experiência síncrona

A arquitetura pode ser assíncrona internamente sem obrigar o usuário a trabalhar de forma assíncrona.

Exemplo:

```text
sk ipm organization create --name acme --wait
```

Fluxo:

```mermaid
sequenceDiagram
    participant CLI
    participant Receiver
    participant ControlLoop

    CLI->>Receiver: POST /v1/ipm/organizations
    Receiver-->>CLI: 202 + operationId

    loop polling
        CLI->>Receiver: GET /v1/ipm/organizations/<id>
        Receiver-->>CLI: current state
    end

    Note over CLI: phase = Ready
```

O `--wait` é uma conveniência do cliente.

Não altera o modelo interno.

# 41. Console, projeções e auditoria

O Manager não deve conhecer detalhes da interface. O Console, a auditoria, as métricas, os alertas e outros consumidores (billing, analytics) consomem `manager.updated` e os demais eventos e constroem suas próprias projeções, sem alterar o Manager.

A auditoria não deve ser necessária para a operação normal do control loop: ela é um consumidor.

# 42. Recuperação após restart

Os componentes devem poder reiniciar sem perder a capacidade de convergir.

Cada componente reinicia reconstruindo o último `desired` e o último `observed` de cada recurso a partir da mensageria. O estado em memória é descartável. Observer, Reconciler e Executor não acessam o SSOT (ver *Estado do Reconciler*).

Para evitar rajadas após o restart de muitos componentes, a reconciliação inicial deve usar jitter e limite de mensagens pendentes.

# 43. Recuperação após perda de mensagem

Caso uma mensagem seja perdida:

A retenção do último estado pela mensageria e a reconciliação periódica permitem recuperação.

# 44. Padrão de dependências

A direção de dependência é: Receiver, Manager, Observer, Reconciler e Executor dependem da mensageria; Observer e Executor dependem do sistema externo; o Manager depende do SSOT.

Não deve existir:

```text
Reconciler → Executor diretamente
Receiver → Executor diretamente
Receiver → Observer diretamente
Observer → Executor diretamente
```

quando o objetivo for comunicação entre componentes do control loop.

Somente o Manager escreve no SSOT; o Receiver o consulta apenas para leitura. Observer, Reconciler e Executor não acessam o SSOT e obtêm o estado de que precisam pela mensageria.

# 45. Resource Control Loop como padrão

O padrão se abstrai para qualquer recurso:

```text
Resource
    │
    ├── Desired
    │
    ├── Observed
    │
    ├── Lifecycle
    │
    ├── Conditions
    │
    └── Generations
```

O fluxo do padrão é o descrito em *Modelo geral*.

# 46. Aplicação à Organization

A Organization é um recurso do módulo `ipm` (`sk ipm organization`, decisão 0016), criado por um usuário registrado (a Account, do módulo `core`), que passa a ser o dono dela.

Para Organization, o Executor escreve em uma organização do Zitadel e o Observer a lê. O Executor escreve a organização (decisão 0038), de forma idempotente: na criação, a organização no Zitadel, com o `resourceId` como ID; na alteração, renomeia e ativa ou desativa a organização (`platformAccess` `granted` ou `revoked`); na remoção, a remove. Com a organização ativa, ele também a **prepara para os usuários** (campo gerenciado `userAccess`, decisão 0081): o Project Grant do projeto de roles do `ipm` com exatamente o catálogo `grantableRole` do contrato, e os papéis das contas do `ipm/user` na organização e no Grant, acrescentando só o que falta. O Observer lê o Grant e os papéis, e o Reconciler trata a falta como divergência (`Drift`). A remoção da organização leva o Grant e os papéis.

O Executor da Organization **não cria usuários nem autoriza o dono**: o dono (`ownerAccountId`, o usuário autenticado que a criou) já existe, pelo cadastro (seção seguinte), e já tem as roles de ação no projeto. Como o dono vive na organização `core` do Zitadel, e não na organização criada, o token não identifica a Organization: o Receiver decide o pertencimento pelo `ownerAccountId` guardado na plataforma (decisão 0010).

Os recursos derivados em outros sistemas (namespace do OpenBao, do Kubernetes) não são escritos por este Executor: são recursos dos próprios módulos, que referenciam o `organizationId`. Assim, cada Executor escreve em um único sistema externo.

O Executor cria a organização no Zitadel informando o `resourceId` como ID da organização (`organization_id`), em vez de deixar o Zitadel gerá-lo. Assim, o ID da organização no Zitadel é o mesmo `resourceId` (`SCHEMA.md`, *Organization e identificadores derivados*), e uma criação repetida (retry, reentrega) não produz uma segunda organização. O Zitadel responde HTTP 409 a um ID ou nome já usado (verificado na v4.19.4); o Executor então lê a organização pelo ID: se existe com o nome esperado, é sucesso idempotente (o mesmo vale para o Project Grant, que também responde 409 quando repetido); se existe com outro nome, ou não existe, é falha permanente.

Antes de publicar `requested`, o Receiver exige solicitante autenticado, com e-mail verificado e a role `ipm.organization.create`. A **cota** de Organizations por dono é aplicada pelo Manager, na mesma unidade atômica do pedido, com trava consultiva por dono (decisão 0010): a pré-checagem do Receiver não basta para criações concorrentes. Nomes reservados e já existentes são rejeitados como `validation`.

Papéis (um projeto e uma imagem em `features/ipm/organization/`, decisão 0063):

```text
ipm-organization-receiver
ipm-organization-manager
ipm-organization-publisher
ipm-organization-observer
ipm-organization-reconciler
ipm-organization-executor
```

O comando `sk ipm organization` pertence ao CLI da plataforma (`clients/cli`), que é cliente do Receiver. Estado: os seis componentes existem e o loop fecha em dev contra o Zitadel (`features/ipm/organization`, decisão 0038); o `observed` informa `platformAccess` pelo estado da organização (`active` ↔ `granted`) e `organizationState`.

## 46.1 Aplicação à Account

A Account é um recurso da plataforma, no módulo `core` (decisão 0014), criado pelo auto-cadastro (`sk account create`), uma escrita anônima (seção 6.1.2). O Executor escreve em um único sistema externo, o Zitadel:

1. cria o usuário na organização `register`, com o `resourceId` como ID e **sem senha**: o `desired` da Account não tem senha, porque `desired` fica retido no SSOT e na mensageria (`SCHEMA.md`);
2. o Zitadel envia o e-mail "Verificar e-mail" na criação, e a pessoa confirma o e-mail e define a senha na página desse link (um e-mail só; o Executor não pede `password_reset`). A senha nunca passa por CLI, Receiver, SSOT nem mensageria;
3. autoriza o usuário nos projetos de roles dos módulos, que pertencem à organização `core` e são delegados à `register` por um Project Grant cada (decisão 0032) (a autorização é criada no contexto da `register`, e só roles do Project Grant são aceitas), com o conjunto de roles de ação do usuário cadastrado (`ipm.organization.create`, `ipm.organization.get`, `ipm.organization.list`, `ipm.organization.update`, `ipm.organization.delete`, `core.account.get` e `core.account.delete`).

Quando o e-mail já está cadastrado no SSOT, o Manager rejeita o pedido (`validation`) sem criar nada; quando ele só existe no Zitadel, a criação do Executor falha de forma permanente (`Rejected`). O Zitadel responde `AlreadyExisting` (HTTP 400, id `COMMAND-7yiox1isql`, verificado na v4.19.4) a um ID ou e-mail já usado, e o Executor lê o usuário pelo ID: se existe com o e-mail esperado, é sucesso idempotente. Em todos os casos o solicitante anônimo recebe o mesmo `202`, sem revelar se o e-mail existia. O `desired` com `lifecycle = absent` não carrega dados pessoais (decisão 0014).

Componentes (projetos em `features/core/account/`): `core-account-receiver`, `core-account-manager`, `core-account-publisher`, `core-account-observer`, `core-account-reconciler` e `core-account-executor`. O comando `sk account create` pertence ao CLI da plataforma.

# 47. Aplicação a outros recursos

O mesmo padrão se aplica a Agent, Runner e Tool. Mudam apenas o sistema externo e os componentes específicos do recurso:

| Recurso | Sistema externo alterado pelo Executor e lido pelo Observer |
|---|---|
| Agent | Agent Runtime |
| Runner | Runner Runtime |
| Tool | External Tool Provider |

Cada recurso possui seu próprio `desired`, `observed`, Reconciler, Executor e Observer.

# 48. Componentes por papel

A plataforma implementa **cada papel de cada tipo de recurso como um componente com processo e contêiner próprios** (decisões 0015 e 0063). A feature (`<módulo>/<tipo>`) é **um projeto e uma imagem**: código, dependências, testes, `Dockerfile`, versão e configuração são da feature, e cada papel roda como contêiner à parte, escolhido pelo `command`. Fica em `features/<módulo>/<tipo>/`, com `src/<módulo>_<tipo>/<papel>/` e `src/<módulo>_<tipo>/common/`.

Regras:

- **Papéis isolados pela credencial, não pela imagem.** Cada papel tem o seu processo, as suas variáveis e segredos, o seu papel de banco, a sua identidade no NATS e a sua conta no provedor; ter o código de um papel na imagem de outro não dá privilégio. Nenhum papel importa outro (um teste confere): só o `common/`, que reúne o que é igual em todos (configuração, mensageria, ciclo de vida, banco, token da conta de serviço, contratos gerados e logging). O código comum existe uma vez por feature; entre features continua duplicado, com fonte única onde houver (decisão 0046).
- **Artefatos neutros compartilhados.** O que é comum é independente de linguagem: contratos em JSON Schema, OpenAPI de cada Receiver, SQL (tabelas, outbox e views), a especificação das mensagens, as convenções de log, métrica e trace, e uma **suíte de testes e2e black-box** por tipo (`features/<módulo>/<tipo>/tests/e2e`, não é um componente), que valida o contrato pela rede e deve passar para qualquer implementação.
- **Estrutura interna.** Todo componente separa regra (`domain/`, pura e sem I/O), orquestração (`handlers/` ou `engine/`), adaptadores (`store/`, `provider/`, `transport/`, `http/`) e a entrada (o `main.py` de cada papel), com a dependência em um sentido só e o `domain` sem importar adaptadores (decisão 0017). No Executor e no Observer, o acesso ao sistema externo é dividido em `provider/` (só a conexão autenticada) e `drivers/` (um por sub-recurso, escrita no Executor e leitura no Observer, espelhados pelo nome; decisão 0073).
- **Comunicação.** Somente pela mensageria. Exceção: o SSOT, em que o Manager escreve, o Receiver lê as views e o Publisher lê e marca o outbox (seção 44).
- **O Receiver contém a sua autenticação e autorização.** Não há serviço de autenticação compartilhado no caminho de uma requisição.
- **O Manager é dono do esquema do tipo.** O código das migrações é do Manager, fica em `migrations/` da feature e executa como etapa de implantação com o papel administrativo do banco, nunca com o papel de runtime (`SSOT.md`, seção 16).
- **Criação incremental.** Um componente é criado quando o seu papel é necessário. A ordem usual é `receiver`, `manager` e `publisher`, depois `observer`, `reconciler` e `executor`. Um papel ainda inexistente não é uma lacuna do padrão, mas uma etapa do recurso.
- **Ambientes.** Em dev, Docker Compose espelha o que será implantado: um serviço por papel, todos com a imagem da feature. Em stg e prd, Kubernetes com CI/CD e GitOps, com um Deployment por papel e a versão da imagem da feature.

O padrão continua definindo **responsabilidades** (seção 3.7). Dois papéis só voltam ao mesmo processo por decisão registrada que mostre, com evidência, que a separação não se justifica.

# 49. Critérios que sustentam a separação

A separação é a regra porque, entre os papéis do loop, há diferenças relevantes em:

```text
security boundary
scaling profile
failure domain
deployment lifecycle
resource consumption
external dependencies
credentials
availability requirements
```

Exemplo:

```text
Observer
    → read-only credential

Executor
    → write credential
```

Essa diferença já constitui uma forte justificativa para separação.

# 50. Evitar fragmentação artificial

A separação é por **papel e por tipo de recurso**, e não por camada técnica. Não criar componentes que:

- não possuam fronteira clara de responsabilidade;
- existam apenas para dividir código que sempre muda, escala e falha junto;
- dependam de outro componente por chamada síncrona dentro do loop.

O objetivo é **separação de responsabilidades com contratos explícitos**, e não a maximização do número de projetos.

# 51. Anti-padrões

## 51.1 Receiver executando provider

```text
Receiver → Zitadel
```

Evitar.

## 51.2 Reconciler executando provider

```text
Reconciler → Zitadel
```

Evitar quando existir Executor.

## 51.3 Observer corrigindo drift

```text
Observer → UPDATE
```

Evitar.

## 51.4 Manager executando operações externas

```text
Manager → POST provider
```

Evitar.

## 51.5 Reconciler dependendo de uma única mensagem

O Reconciler não deve depender da sequência:

```text
desired
  ↓
observed
  ↓
reconcile
```

Ele deve conseguir reconciliar a partir dos estados atuais.

## 51.6 Convergência baseada em ACK

```text
ACK = Ready
```

Incorreto.

## 51.7 Control loop baseado somente em eventos

Eventos aceleram a convergência, mas o sistema deve possuir mecanismos de recuperação. A reconciliação periódica é obrigatória.

# 52. Segurança do loop

Os requisitos de segurança do Resource Control Loop são definidos em [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md). Este documento mantém apenas as invariantes que o padrão exige:

- cada serviço (módulo, tipo e papel) possui identidade própria e publica somente no seu próprio emissor e tipo de recurso;
- a `action` é a mensagem mais privilegiada do loop: somente o Reconciler a publica e somente o Executor a consome;
- o Executor revalida a `action` contra o `desired` vigente e consulta o desfecho do `actionId` antes de escrever no sistema externo;
- `observed` inconclusivo (`unknown`) ou desatualizado não autoriza `Action`;
- a identidade do solicitante (`requestedBy`) acompanha a operação de ponta a ponta;
- segredos trafegam somente por referência;
- a credencial de escrita pertence exclusivamente ao Executor;
- nenhum serviço de runtime possui permissão de purge ou de administração do transporte.

# 53. Proteções de carga e estabilidade

O loop corrige continuamente a realidade. Sem limites, ele pode sobrecarregar o provider ou disputar indefinidamente com outro agente.

- **Limite de taxa e backpressure:** o Executor limita a concorrência e a taxa de chamadas ao provider e respeita sinais de limite do provider (por exemplo, `Retry-After`).
- **Flapping:** quando o mesmo recurso diverge repetidamente após convergir, o Manager registra a condition `DriftLoop` e o Reconciler aplica backoff crescente até intervenção, em vez de corrigir indefinidamente.
- **Restart em massa:** jitter na reconciliação inicial e periódica, e limite de mensagens pendentes por consumidor.
- **Observação envelhecida:** a condition `ObservationStale` e o alerta correspondente sinalizam recursos sem observação conclusiva dentro do prazo do domínio.
- **Métricas mínimas:** latência até a convergência, idade da última reconciliação por recurso, idade do último `observed`, quantidade de `action` pendentes e taxa de falha por provider (ver `NATS.md`, observabilidade).
- **Pontos únicos de falha:** Manager, PostgreSQL e mensageria são dependências críticas. Com o Manager indisponível, o loop continua para o `desired` já publicado, mas não aceita novos pedidos nem atualiza o SSOT.

# 54. Propriedades desejadas

Uma implementação madura do Resource Control Loop deve possuir:

```text
Declarative
Idempotent
Eventually Consistent
Recoverable
Observable
Auditable
Scalable
Least Privilege
Provider Independent
Transport Independent
```

# 55. Checklist de implementação

Antes de considerar um novo recurso conforme ao padrão, verificar:

### Resource

- [ ] Existe `resourceId` estável?
- [ ] Existe `desired`?
- [ ] Existe `observed`?
- [ ] Existe `desiredGeneration` quando necessário?
- [ ] Existe `observedGeneration` quando necessário?
- [ ] Lifecycle está definido?
- [ ] Conditions estão definidas?

### Manager

- [ ] É o owner do SSOT?
- [ ] É responsável pelo lifecycle?
- [ ] Publica `desired`?
- [ ] Processa `observed`?
- [ ] Não executa provider diretamente?
- [ ] Persiste e registra a publicação de `desired` na mesma transação (outbox)?
- [ ] Conta as falhas por geração, marca `Failed` e suspende a reconciliação no `desired`?
- [ ] Registra `ObservationStale` quando não há observação conclusiva no prazo?

### Observer

- [ ] É read-only?
- [ ] Consegue observar a realidade?
- [ ] Publica `observed`?
- [ ] Executa periodicamente?
- [ ] Informa `observedAt`?
- [ ] Distingue `present`, `absent` e `unknown`?
- [ ] Observa apenas os recursos da sua partição?
- [ ] Observa após `completed` e `failed`, com `causationId` do resultado?

### Reconciler

- [ ] Consome `desired`?
- [ ] Consome `observed`?
- [ ] Compara os dois estados?
- [ ] Pode ser acionado por qualquer alteração?
- [ ] Reavalia periodicamente?
- [ ] Só decide com `desired` e `observed` conclusivos e dentro do limite de validade?
- [ ] Não reemite `action` pendente?
- [ ] Respeita `desired` suspenso e aplica backoff a partir do último `failed`?
- [ ] Aguarda a observação causada pelo resultado antes de decidir de novo?
- [ ] O `actionId` inclui a observação que motivou a decisão?
- [ ] A comparação entre `desired` e `observed` está definida para o recurso?
- [ ] Produz `action`?
- [ ] Não executa a ação diretamente?

### Executor

- [ ] Consome `action`?
- [ ] Possui somente os privilégios necessários?
- [ ] Revalida a `action` contra o `desired` vigente?
- [ ] Consulta o desfecho do `actionId` antes de executar?
- [ ] Possui chave de correlação com o recurso externo?
- [ ] Serializa a execução por recurso (*single-flight*)?
- [ ] Limita taxa e concorrência contra o provider?
- [ ] Executa operações de forma idempotente?
- [ ] Publica `completed` ou `failed`?
- [ ] Não decide o estado desejado?

### Componentes

- [ ] Cada papel roda como processo e contêiner próprios, sem importar outro papel (só o `common/` da feature)?
- [ ] O Receiver tem a sua autenticação e autorização?
- [ ] O Manager é dono do código das migrações do tipo, executadas como etapa de implantação com papel administrativo?
- [ ] O Publisher é um papel próprio, com papel de banco e identidade de mensageria próprios?
- [ ] Os contratos (JSON Schema, OpenAPI, SQL, mensagens) são verificados pelos testes e2e black-box?
- [ ] A estrutura interna segue a decisão 0017 (`domain/` puro, orquestração, adaptadores, `main.py`) e o `domain/` não importa adaptador?

### Messaging

- [ ] Subject segue a gramática oficial?
- [ ] `messageType` é válido?
- [ ] `operation` é semanticamente preciso?
- [ ] `messageId` é único?
- [ ] `correlationId` é utilizado quando necessário?
- [ ] `causationId` é utilizado quando necessário?
- [ ] Reentrega é suportada?
- [ ] Ordering é explicitamente definido quando necessário?

# 56. Fonte de verdade

Este documento define o **Resource Control Loop** como padrão arquitetural da plataforma.

`MESSAGING.md` define a semântica das mensagens.

`NATS.md` define a implementação da mensageria utilizando NATS e NATS JetStream.

`SCHEMA.md` define os contratos formais e a evolução dos schemas.

`RESOURCE-CONTROL-SECURITY.md` define os requisitos de segurança do padrão.

A decisão `0015` (`.decisions/`) define o modelo de componentes por papel.

O contrato do Resource define:

```text
Resource
Desired
Observed
Lifecycle
Conditions
Generations
```

O Resource Control Loop define como esses conceitos participam de um processo contínuo de convergência.

**O sistema não é considerado concluído quando uma ação é executada. O sistema é considerado convergido quando o `Observed` demonstra que a realidade corresponde ao `Desired`, conforme as regras do recurso.**