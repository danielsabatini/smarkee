# Resource Control Loop

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

Na implementação atual, NATS JetStream é utilizado como mecanismo de mensageria e PostgreSQL como SSOT, mas esses componentes são detalhes de implementação.

O Resource Control Loop é baseado no princípio:

```text
Desired → Observe → Reconcile → Act → Observe → Converge
```

# 2. Objetivo

Este documento define o padrão arquitetural oficial para componentes que gerenciam recursos da plataforma.

O objetivo é estabelecer uma estrutura consistente para recursos como:

```text
Tenant
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

O padrão define **responsabilidades arquiteturais**, não uma quantidade obrigatória de processos.

Por exemplo:

```text
Manager
Observer
Reconciler
Executor
```

podem ser:

```text
4 processos
```

ou:

```text
2 processos
```

desde que as responsabilidades permaneçam claramente separadas.

A separação em processos independentes é preferível quando:

- possuem ciclos de escala diferentes;
- possuem permissões diferentes;
- possuem dependências diferentes;
- precisam de isolamento;
- possuem falhas independentes;
- possuem requisitos operacionais diferentes.

## 3.8 Estado do Reconciler

O Manager publica `desired`. O Observer publica `observed`. O Reconciler consome os dois.

O estado do Reconciler é o último `desired` e o último `observed` de cada `resourceId`, obtidos **exclusivamente pela mensageria**. O Reconciler não acessa o SSOT.

```text
Manager  → desired  ┐
                    ├→ Reconciler (último desired + último observed por resourceId)
Observer → observed ┘
```

Regras:

- o estado mantido em memória é um cache descartável: após restart, **cada instância** do Reconciler o reconstrói consumindo o último `desired` e o último `observed` de cada recurso. O consumo é por instância, e não compartilhado entre elas, para que todas possuam o estado completo (`NATS.md`);
- instâncias distintas podem tomar a mesma decisão. Isso é inofensivo porque a `action` possui `actionId` determinístico (ver *Identidade da Action*);
- por isso, o transporte deve reter ao menos a última mensagem de `desired` e de `observed` por recurso (na implementação NATS, ver `NATS.md`);
- o Reconciler não decide enquanto não possuir os dois estados;
- o Reconciler não decide com `observed` inconclusivo ou desatualizado (ver *Observação inconclusiva*).

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
    API[API]

    subgraph Messaging[NATS / Messaging]
        Requested[requested]
        Desired[desired]
        Observed[observed]
        Action[action]
        Completed[completed]
        Updated[updated]
    end

    Manager[Manager<br/>SSOT + Lifecycle]
    Observer[Observer<br/>Reality]
    Reconciler[Reconciler<br/>Decision]
    Executor[Executor<br/>Execution]

    External[External System]

    Client -->|HTTP| API

    API -->|requested| Requested
    Requested --> Manager

    Manager -->|desired| Desired
    Desired --> Reconciler
    Desired --> Observer

    External -->|read| Observer
    Observer -->|observed| Observed
    Observed --> Reconciler

    Reconciler -->|action| Action
    Action --> Executor

    Executor -->|write| External
    Executor -->|completed| Completed

    Completed --> Manager
    Observed --> Manager

    Manager -->|updated| Updated
```

O Observer consome `desired` apenas para saber quais recursos observar. Ele não decide e não compara estados.

# 6. Componentes

# 6.1 API

A API é a porta de entrada do sistema.

Responsabilidades:

- autenticação;
- autorização;
- validação estrutural;
- geração de identificadores;
- criação de contexto de correlação;
- publicação de `requested`;
- consulta do SSOT;
- exposição do estado atual.

A API não deve:

- possuir o SSOT;
- executar reconciliação;
- chamar diretamente o sistema externo;
- implementar lógica de integração com o provider.

Fluxo:

```mermaid
flowchart LR
    CLI[CLI] --> API[API]
    API -->|requested| NATS[NATS]
    NATS --> Manager[Manager]
```

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

Por exemplo, no caso de Tenant, ele não precisa implementar chamadas para Zitadel.

# 6.3 Observer

O Observer transforma realidade externa em `observed`.

Responsabilidades:

- consultar sistemas externos;
- verificar existência;
- consultar configuração;
- coletar estado;
- produzir observações;
- detectar drift;
- executar observação periódica, independentemente de eventos;
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
- possuir lógica de API;
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

# 7. O fluxo completo

O fluxo completo pode ser dividido em seis fases:

```text
1. Request
2. Desired
3. Observation
4. Reconciliation
5. Action
6. Execution
```

Visualmente:

```mermaid
flowchart LR

    A[Request]
    B[Desired]
    C[Observed]
    D[Reconcile]
    E[Action]
    F[Execute]
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
sk ipm tenant create --name acme
```

Fluxo:

```mermaid
sequenceDiagram
    participant CLI
    participant API
    participant NATS
    participant Manager

    CLI->>API: POST /v1/tenants
    API->>NATS: api.requested.ipm.tenant.<id>.create
    NATS->>Manager: requested
    Manager->>Manager: validate + persist
    Manager->>NATS: manager.desired.ipm.tenant.<id>.changed
```

A API retorna rapidamente:

```text
202 Accepted
```

O processamento continua de forma assíncrona.

Requisitos:

- a API aceita uma chave de idempotência no `POST`: a repetição do mesmo pedido não cria outro recurso nem outro `desired`;
- atualizações devem informar a versão do recurso (`resourceVersion`, ver `MESSAGING.md`); uma versão desatualizada é rejeitada, e a atualização não sobrescreve silenciosamente outra concorrente;
- o Manager persiste o recurso e registra a publicação de `desired` na mesma transação (outbox, ver `MESSAGING.md`), evitando o estado `persistido, mas não publicado`.

# 9. Fase 2 — Desired

O Manager estabelece o estado desejado no SSOT.

Exemplo:

```json
{
  "resourceId": "tenant-01",
  "desiredGeneration": 1,
  "desired": {
    "lifecycle": "present",
    "resourceName": "acme"
  }
}
```

Publicação:

```text
manager.desired.ipm.tenant.tenant-01.changed
```

O Desired é uma declaração.

Não significa que o Tenant já existe.

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
- após `completed`, ignora observações anteriores à conclusão ao decidir uma nova ação.

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
reconciler.action.ipm.tenant.<id>.create
```

# 12. O Reconciler possui duas entradas independentes

Esta é uma propriedade fundamental do padrão.

```mermaid
flowchart TB

    D["manager.desired<br/>Desired"]
    O["observer.observed<br/>Observed"]

    D --> R["Reconciler<br/><br/>Desired vs Observed"]
    O --> R

    R --> A["Action"]
```

O Reconciler pode ser acionado por:

```text
Desired mudou
```

ou:

```text
Observed mudou
```

ou:

```text
reconciliation periódica
```

ou:

```text
retry / recovery
```

# 13. Reconcile provocado por mudança em Desired

```mermaid
sequenceDiagram
    participant Manager
    participant NATS
    participant Reconciler
    participant Executor

    Manager->>NATS: desired.changed
    NATS->>Reconciler: desired.changed

    Note over Reconciler: lê Observed atual

    Reconciler->>Reconciler: compare Desired vs Observed
    Reconciler->>NATS: action.create
    NATS->>Executor: action.create
```

O Reconciler não precisa esperar uma nova mensagem `observed`.

Ele utiliza o último `observed` retido em seu estado (ver *Estado do Reconciler*), desde que seja conclusivo e esteja dentro do limite de validade (ver *Observação inconclusiva*).

# 14. Reconcile provocado por mudança em Observed

Este caso é igualmente importante.

Imagine que um administrador altere diretamente o sistema externo.

```mermaid
sequenceDiagram
    participant External as External System
    participant Observer
    participant NATS
    participant Reconciler
    participant Executor

    External->>Observer: Reality changed
    Observer->>NATS: observed.changed
    NATS->>Reconciler: observed.changed

    Reconciler->>Reconciler: compare Desired vs Observed
    Reconciler->>NATS: action.update
    NATS->>Executor: action.update
```

Esse mecanismo permite detectar e corrigir **drift**.

# 15. Drift

Drift ocorre quando:

```text
Desired != Observed
```

Exemplo:

```mermaid
flowchart LR

    D["Desired<br/>Tenant exists"]
    O["Observed<br/>Tenant absent"]

    D --> R["Reconciler"]
    O --> R

    R --> A["Create"]
```

Outro exemplo:

```mermaid
flowchart LR

    D["Desired<br/>name = ACME"]
    O["Observed<br/>name = ACME Corp"]

    D --> R["Reconciler"]
    O --> R

    R --> A["Update"]
```

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

# 16. Fase 5 — Action

A Action representa uma decisão.

Exemplo:

```text
reconciler.action.ipm.tenant.<id>.create
```

Payload:

```json
{
  "messageType": "action",
  "operation": "create",
  "actionId": "tenant-01.1.create",
  "resourceId": "tenant-01",
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

## 16.1 Identidade da Action

O `actionId` é **determinístico**: derivado de `resourceId`, `desiredGeneration` e `operation`. A mesma decisão sobre o mesmo estado produz o mesmo `actionId`.

- A deduplicação ocorre em três pontos: o publicador usa o `actionId` como chave de deduplicação do transporte (quando suportado), o Reconciler não reemite enquanto houver `action` pendente e o Executor deduplica por `actionId`. Reentrega, reemissão ou decisão duplicada de outra instância não geram uma segunda execução. A deduplicação do Executor é obrigatória e não depende do transporte.
- O Reconciler não reemite uma `action` enquanto houver outra pendente para o recurso (ou seja, sem `completed` ou `failed` correspondente). Ao expirar o prazo de ação definido pelo domínio, ele pode reemitir com o mesmo `actionId`.
- Uma `action` baseada em geração obsoleta é descartada pelo Executor.

O campo é definido em `MESSAGING.md` (envelope).

# 17. Fase 6 — Execution

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

# 18. Completed não significa convergência

Este princípio é obrigatório.

```text
executor.completed
        ≠
resource converged
```

`completed` significa:

> A operação solicitada foi executada com sucesso.

A convergência somente pode ser confirmada pela observação compatível.

```mermaid
flowchart LR

    A["Action.create"] --> E["Executor"]
    E --> C["completed"]
    E --> X["External System"]
    X --> O["Observed presence=present"]

    O --> R["Reconciler"]

    R --> V{"Converged?"}
    V -->|Yes| Ready["Ready"]
```

# 19. Nova observação

Após a execução, o Observer verifica novamente.

```mermaid
sequenceDiagram
    participant Executor
    participant External
    participant Observer
    participant NATS

    Executor->>External: Create
    External-->>Executor: Success

    Note over Observer: próxima observação
    Observer->>External: GET organization
    External-->>Observer: Organization exists
    Observer->>NATS: observed presence=present
```

Agora:

```text
Desired = present
Observed = present
```

# 20. Convergência

O Reconciler compara novamente:

```mermaid
flowchart TB

    D["Desired<br/>present"]
    O["Observed<br/>present"]

    D --> R["Reconciler"]
    O --> R

    R --> C{"Equal?"}

    C -->|Yes| N["No Action"]
    C -->|No| A["Action"]
```

Resultado:

```text
No Action
```

O recurso convergiu.

## 20.1 Comparação entre Desired e Observed

A pergunta "Desired == Observed?" deve ter definição explícita para cada recurso:

- **campos gerenciados:** apenas os campos declarados em `desired` participam da comparação; campos não declarados não geram drift;
- **normalização:** os valores são normalizados antes da comparação (caixa, ordenação de listas, formatação), conforme o contrato do recurso;
- **defaults do provider:** valores preenchidos pelo provider e não declarados em `desired` não constituem drift;
- **resultado:** iguais → `noop`; diferentes → `Action` determinada pela diferença.

Uma comparação mal definida produz `update` infinito. A definição pertence ao contrato do recurso (`SCHEMA.md`).

# 21. Atualização do SSOT

O Manager recebe a observação e atualiza o Resource.

```mermaid
flowchart LR

    O["observer.observed"]
    O --> M["Manager"]

    M --> DB[(PostgreSQL)]

    DB --> S["Resource<br/>observed + conditions + lifecycle"]

    M --> U["manager.updated"]
```

Exemplo:

```text
lifecycle = Ready
desiredGeneration = 1
observedGeneration = 1
condition = Ready=True
```

# 22. Fluxo completo do Tenant

```mermaid
sequenceDiagram

    participant CLI
    participant API
    participant NATS
    participant Manager
    participant Observer
    participant Reconciler
    participant Executor
    participant Zitadel

    CLI->>API: POST /v1/tenants
    API->>NATS: requested.create

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

    CLI->>API: GET /v1/tenants/<id>
    API-->>CLI: lifecycle=Ready
```

# 23. Fluxo de atualização

```mermaid
flowchart TB

    A[Desired changed]
    B[desiredGeneration++]
    C[Observed old generation]
    D[Reconciler]
    E[Action update]
    F[Executor]
    G[External System]
    H[Observer]
    I[Observed new generation]
    J[Converged]

    A --> B
    B --> D
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> D
    D --> J
```

# 24. Fluxo de remoção

A remoção também é declarativa.

```mermaid
flowchart TB

    D["Desired<br/>lifecycle = absent"]
    O["Observed<br/>lifecycle = present"]

    D --> R["Reconciler"]
    O --> R

    R --> A["Action: delete"]
    A --> E["Executor"]
    E --> X["External System"]

    X --> B["Observer"]
    B --> O2["Observed: absent"]

    O2 --> R
    R --> C["Converged"]
```

A plataforma não precisa representar a exclusão como um comando imperativo no `desired`.

Após a convergência da remoção, o Manager remove o recurso do SSOT. O último `desired` (`lifecycle=absent`) permanece no transporte como tombstone até uma limpeza administrativa; Reconciler e Observer ignoram recurso com `lifecycle=absent` já convergido (`NATS.md` e `RESOURCE-CONTROL-SECURITY.md`).

**Limitação conhecida:** este padrão não define a ordem de remoção entre recursos dependentes (por exemplo, um Tenant com Agents). Enquanto não houver regra própria, a remoção de um recurso com dependentes deve ser tratada pelo domínio.

# 25. Fluxo de falha

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

Uma falha de execução não deve destruir o Desired.

O Desired permanece como fonte da intenção.

Isso permite retry e recuperação.

Retry, backoff, limite de tentativas e quarentena seguem `NATS.md`. No nível do recurso:

- falha transitória mantém o recurso em `Reconciling`, com nova tentativa sob backoff;
- ao esgotar as tentativas, o recurso passa a `Failed` e registra a causa em `conditions`;
- de `Failed`, o recurso só volta a `Reconciling` por nova geração de `desired` ou por intervenção explícita, e não em ciclo contínuo contra o provider.

# 26. Falha após alteração externa

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

# 27. Reconciliation periódica

Eventos não devem ser a única forma de disparar reconciliação.

O sistema deve possuir reconciliação periódica:

```mermaid
flowchart LR

    Timer["Periodic Trigger"]
    Timer --> Reconciler

    Desired["Current Desired"]
    Observed["Current Observed"]

    Desired --> Reconciler
    Observed --> Reconciler

    Reconciler --> Decision["Reconcile"]
```

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

# 28. Reconciliation é idempotente

Uma mesma mensagem pode provocar múltiplas reconciliações.

```mermaid
flowchart TB

    D1["desired.changed"]
    D2["desired.changed<br/>duplicate"]
    O["observed presence=absent"]

    D1 --> R["Reconciler"]
    D2 --> R
    O --> R

    R --> A["action.create"]

    A --> E["Executor"]

    E --> X["External System"]

    X -->|already exists| Success["No harmful side effect"]
```

O Executor também deve ser idempotente ou utilizar mecanismos que tornem a operação segura.

Para que a repetição de um `create` (por exemplo, após timeout) não duplique o recurso, o Executor deve possuir uma chave de correlação com o recurso externo: um identificador externo determinístico, uma chave de idempotência aceita pelo provider ou uma consulta prévia quando o provider não garante unicidade.

# 29. Idempotência em cada camada

```mermaid
flowchart LR

    API["API"]
    Manager["Manager"]
    Reconciler["Reconciler"]
    Executor["Executor"]
    External["External"]

    API --> Manager
    Manager --> Reconciler
    Reconciler --> Executor
    Executor --> External

    API -.->|request idempotency| API
    Manager -.->|resource constraints| Manager
    Reconciler -.->|generation comparison| Reconciler
    Executor -.->|safe execution| Executor
    External -.->|provider semantics| External
```

Cada camada possui uma estratégia diferente.

Não existe uma única técnica universal de idempotência.

# 30. Mensageria

A comunicação utiliza o modelo semântico definido em `MESSAGING.md`.

Formato:

```text
<emitter>.<messageType>.<module>.<resourceType>.<resourceId>.<operation>
```

Exemplos:

```text
api.requested.ipm.tenant.<id>.create

manager.desired.ipm.tenant.<id>.changed

observer.observed.ipm.tenant.<id>.changed

reconciler.action.ipm.tenant.<id>.create

executor.completed.ipm.tenant.<id>.create

manager.updated.ipm.tenant.<id>.changed
```

O resultado da observação (`present`, `absent` ou `unknown`) é informado no campo `presence`, e não no endereço. Cada `messageType` é persistido em seu próprio Stream, com a retenção da sua classe de mensagem (trabalho, estado ou fato), conforme `NATS.md`.

# 31. Quem publica e quem consome

O padrão define explicitamente:

| Mensagem | Publicador | Consumidores principais |
|---|---|---|
| `requested` | API | Manager |
| `desired` | Manager | Reconciler, Observer, Executor (revalidação, somente leitura), outros interessados |
| `observed` | Observer | Reconciler, Manager, outros consumidores |
| `action` | Reconciler | Executor |
| `completed` | Executor | Manager, Observer, Reconciler (rastreio de action pendente), auditoria |
| `updated` | Manager | Console, auditoria, métricas, consumidores |
| `failed` | Executor/componente responsável | Manager, Reconciler (rastreio de action pendente), observabilidade, retry |

O consumidor não deve ser codificado no subject.

# 32. Matriz de responsabilidades

| Responsabilidade | API | Manager | Observer | Reconciler | Executor |
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

# 33. Separação de privilégios

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
API
Manager
Observer
Reconciler
```

quando não forem necessárias.

Cada componente deve possuir identidade própria no barramento, com permissões de publicação e assinatura restritas ao seu papel. Os requisitos completos estão em `RESOURCE-CONTROL-SECURITY.md`.

# 34. Separação de falhas

Cada componente possui um domínio de falha diferente.

```mermaid
flowchart LR

    API["API"]
    Manager["Manager"]
    Observer["Observer"]
    Reconciler["Reconciler"]
    Executor["Executor"]

    API -.-> FA["API failure"]
    Manager -.-> FM["Persistence failure"]
    Observer -.-> FO["Provider read failure"]
    Reconciler -.-> FR["Decision failure"]
    Executor -.-> FE["Provider write failure"]
```

O objetivo é permitir que uma falha em um componente não exija indisponibilidade de toda a plataforma.

# 35. Escalabilidade

Os componentes podem escalar independentemente.

```mermaid
flowchart TB

    NATS[NATS]

    NATS --> M1[Manager 1]
    NATS --> M2[Manager 2]

    NATS --> O1[Observer 1]
    NATS --> O2[Observer 2]

    NATS --> R1[Reconciler 1]
    NATS --> R2[Reconciler 2]
    NATS --> R3[Reconciler 3]

    NATS --> E1[Executor 1]
    NATS --> E2[Executor 2]
```

A quantidade de instâncias deve ser determinada pelo comportamento do componente.

Por exemplo:

```text
Executor
    → pode exigir escala baseada em chamadas ao provider

Observer
    → pode exigir escala baseada em quantidade de recursos

Reconciler
    → pode exigir escala baseada em eventos

Manager
    → pode exigir escala baseada em throughput do SSOT
```

# 36. Concorrência

A unidade natural de concorrência deve ser o recurso.

Exemplo:

```text
Tenant A → reconciliation independente
Tenant B → reconciliation independente
Tenant C → reconciliation independente
```

```mermaid
flowchart TB

    NATS[NATS]

    NATS --> RA[Reconciler<br/>Tenant A]
    NATS --> RB[Reconciler<br/>Tenant B]
    NATS --> RC[Reconciler<br/>Tenant C]
```

Quando houver necessidade de serialização, ela deve ser definida explicitamente por `resourceId` ou `orderingKey`.

Não assumir ordenação global.

Para cada `resourceId`, apenas uma `action` deve estar em execução por vez (*single-flight*). Várias instâncias do Reconciler podem decidir o mesmo recurso; a serialização é responsabilidade do **Executor**, e não do Reconciler. O Executor deve garantir uma única execução por vez por recurso (por exemplo, consumindo uma `action` por vez por serviço) e permanecer idempotente, pois sob falha uma `action` pode ser entregue a outra instância enquanto a anterior ainda executa (`NATS.md`).

# 37. DesiredGeneration

A geração identifica uma versão lógica do estado desejado.

```mermaid
flowchart LR

    G1["DesiredGeneration 1"]
    G2["DesiredGeneration 2"]
    G3["DesiredGeneration 3"]

    G1 --> G2
    G2 --> G3
```

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

# 38. ObservedGeneration

O sistema externo não conhece a geração do `desired`. Por isso, a convergência **não** é determinada por `observedGeneration`, e sim pela comparação de conteúdo entre `desired` e `observed` (ver *Comparação entre Desired e Observed*).

A geração serve para:

- descartar uma `action` baseada em geração obsoleta;
- identificar a que geração uma condition se refere.

`observedGeneration` só é confiável quando a geração é registrada no próprio recurso externo (por exemplo, como metadado gravado pelo Executor) e lida pelo Observer:

```text
Desired:
generation = 5

Recurso externo (metadado gravado pelo Executor):
generation = 4
```

Indica que o recurso externo ainda não reflete a geração 5.

Quando o provider não permite esse registro, `observedGeneration` não deve ser usado como evidência de convergência.

# 39. Lifecycle

O lifecycle do Resource Control Loop é definido no recurso, não na mensageria.

Exemplo:

```mermaid
stateDiagram-v2

    [*] --> Pending
    Pending --> Reconciling
    Reconciling --> Ready
    Reconciling --> Failed
    Ready --> Reconciling
    Ready --> Deleting
    Failed --> Reconciling
    Deleting --> [*]
```

Um recurso pode permanecer em:

```text
Reconciling
```

durante múltiplos ciclos.

Isso é esperado.

O estado `Failed` é terminal para o ciclo automático: a saída dele segue as regras descritas em *Fluxo de falha*.

# 40. Conditions

Conditions representam fatos ou condições consolidadas do recurso.

Exemplo:

```json
{
  "type": "Ready",
  "status": "True",
  "reason": "Reconciled",
  "message": "Tenant exists in Zitadel",
  "observedGeneration": 1,
  "lastTransitionAt": "2026-10-04T00:00:00Z"
}
```

O lifecycle e as conditions são persistidos no SSOT pelo Manager.

# 41. Operation

Uma operação acompanha uma solicitação assíncrona.

Exemplo:

```text
operationId
operationType
resourceId
desiredGeneration
status
createdAt
updatedAt
completedAt
```

A Operation não deve ser confundida com o Resource.

```text
Resource
    = objeto gerenciado

Operation
    = processamento de uma solicitação
```

# 42. CLI e experiência síncrona

A arquitetura pode ser assíncrona internamente sem obrigar o usuário a trabalhar de forma assíncrona.

Exemplo:

```text
sk ipm tenant create --name acme --wait
```

Fluxo:

```mermaid
sequenceDiagram
    participant CLI
    participant API
    participant ControlLoop

    CLI->>API: POST /tenants
    API-->>CLI: 202 + operationId

    loop polling
        CLI->>API: GET /tenants/<id>
        API-->>CLI: current state
    end

    Note over CLI: lifecycle = Ready
```

O `--wait` é uma conveniência do cliente.

Não altera o modelo interno.

# 43. Console e projeções

O Manager não deve conhecer detalhes da interface.

O Console pode consumir:

```text
manager.updated
```

e construir sua própria projeção.

```mermaid
flowchart LR

    Manager["Manager"]
    NATS["NATS"]
    Console["Console Projection"]

    Manager -->|updated| NATS
    NATS --> Console
```

Outros consumidores podem existir:

```text
Audit
Metrics
Alerts
Billing
Analytics
```

sem alterar o Manager.

# 44. Auditoria

Eventos de domínio podem ser consumidos por uma camada de auditoria.

```mermaid
flowchart TB

    NATS[NATS]

    NATS --> Audit[Audit]
    NATS --> Console[Console]
    NATS --> Metrics[Metrics]
    NATS --> Alerts[Alerts]
```

A auditoria não deve ser necessária para a operação normal do control loop.

Ela é um consumidor.

# 45. Recuperação após restart

Os componentes devem poder reiniciar sem perder a capacidade de convergir.

```mermaid
flowchart LR

    Restart[Component Restart]

    Restart --> ReadDesired[Replay do último desired por recurso]
    Restart --> ReadObserved[Replay do último observed por recurso]

    ReadDesired --> Reconcile[Reconcile]
    ReadObserved --> Reconcile

    Reconcile --> Continue[Continue Control Loop]
```

O estado em memória é descartável. Observer, Reconciler e Executor não acessam o SSOT e reconstroem o que precisam pela mensageria (ver *Estado do Reconciler*).

Para evitar rajadas após o restart de muitos componentes, a reconciliação inicial deve usar jitter e limite de mensagens pendentes.

# 46. Recuperação após perda de mensagem

Caso uma mensagem seja perdida:

```mermaid
flowchart TB

    Desired[Desired persisted]
    Message[Desired message lost]
    Timer[Periodic reconciliation]

    Desired --> Message
    Message -->|lost| Timer

    Timer --> Reconciler
    Desired --> Reconciler
    Observed[Observed] --> Reconciler

    Reconciler --> Action
```

A retenção do último estado pela mensageria e a reconciliação periódica permitem recuperação.

# 47. Padrão de dependências

A direção de dependência deve ser:

```mermaid
flowchart LR

    API --> Messaging
    Manager --> Messaging
    Observer --> Messaging
    Reconciler --> Messaging
    Executor --> Messaging

    Observer --> External
    Executor --> External

    Manager --> SSOT
```

Não deve existir:

```text
Reconciler → Executor diretamente
API → Executor diretamente
API → Observer diretamente
Observer → Executor diretamente
```

quando o objetivo for comunicação entre componentes do control loop.

Somente o Manager escreve no SSOT; a API o consulta apenas para leitura. Observer, Reconciler e Executor não acessam o SSOT e obtêm o estado de que precisam pela mensageria.

# 48. Resource Control Loop como padrão

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

# 49. Aplicação ao Tenant

Para Tenant:

```mermaid
flowchart TB

    TenantDesired["Tenant Desired"]
    TenantObserved["Tenant Observed"]

    TenantDesired --> Reconciler["Tenant Reconciler"]
    TenantObserved --> Reconciler

    Reconciler --> Action["Create / Update / Delete"]
    Action --> Executor["Tenant Executor"]

    Executor --> Zitadel["Zitadel Organization"]

    Zitadel --> Observer["Tenant Observer"]
    Observer --> TenantObserved
```

Componentes:

```text
cli-ipm-tenant
api-ipm-tenant
srv-ipm-tenant-manager
srv-ipm-tenant-observer
srv-ipm-tenant-reconciler
srv-ipm-tenant-executor
```

# 50. Aplicação a outros recursos

O mesmo padrão se aplica a Agent, Runner e Tool. Mudam apenas o sistema externo e os componentes específicos do recurso:

| Recurso | Sistema externo alterado pelo Executor e lido pelo Observer |
|---|---|
| Agent | Agent Runtime |
| Runner | Runner Runtime |
| Tool | External Tool Provider |

Cada recurso possui seu próprio `desired`, `observed`, Reconciler, Executor e Observer.

# 51. O padrão não exige seis processos

Um recurso simples pode implementar:

```mermaid
flowchart LR

    API --> Service
    Service --> External
```

desde que internamente mantenha as responsabilidades:

```text
Desired
Observed
Reconciliation
Execution
```

Entretanto, quando os requisitos de escala, segurança ou isolamento justificarem, as responsabilidades podem ser separadas:

```mermaid
flowchart LR

    API
    Manager
    Observer
    Reconciler
    Executor

    API --> Manager
    Manager --> Observer
    Manager --> Reconciler
    Reconciler --> Executor
```

A decisão deve ser baseada em responsabilidade e operação, não em uma regra artificial de quantidade de serviços.

O formato colapsado é o ponto de partida. A separação em componentes independentes exige justificativa registrada, conforme os critérios de *Quando separar em processos*.

# 52. Quando separar em processos

A separação é recomendada quando houver diferenças relevantes em:

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

# 53. Quando não separar

Evitar fragmentação quando dois componentes:

- sempre escalam juntos;
- possuem exatamente o mesmo ciclo de vida;
- possuem as mesmas permissões;
- possuem as mesmas dependências;
- não possuem necessidade de isolamento;
- não possuem fronteira clara de responsabilidade.

O objetivo é **separação de responsabilidades**, não maximização do número de serviços.

# 54. Anti-padrões

## 54.1 API executando provider

```text
API → Zitadel
```

Evitar.

## 54.2 Reconciler executando provider

```text
Reconciler → Zitadel
```

Evitar quando existir Executor.

## 54.3 Observer corrigindo drift

```text
Observer → UPDATE
```

Evitar.

## 54.4 Manager executando operações externas

```text
Manager → POST provider
```

Evitar.

## 54.5 Reconciler dependendo de uma única mensagem

O Reconciler não deve depender da sequência:

```text
desired
  ↓
observed
  ↓
reconcile
```

Ele deve conseguir reconciliar a partir dos estados atuais.

## 54.6 Convergência baseada em ACK

```text
ACK = Ready
```

Incorreto.

## 54.7 Control loop baseado somente em eventos

Eventos aceleram a convergência, mas o sistema deve possuir mecanismos de recuperação. A reconciliação periódica é obrigatória.

# 55. Segurança do loop

Os requisitos de segurança do Resource Control Loop são definidos em [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md). Este documento mantém apenas as invariantes que o padrão exige:

- cada componente possui identidade própria e publica somente no seu próprio emissor;
- a `action` é a mensagem mais privilegiada do loop: somente o Reconciler a publica e somente o Executor a consome;
- o Executor revalida a `action` contra o `desired` vigente antes de escrever no sistema externo;
- `observed` inconclusivo (`unknown`) ou desatualizado não autoriza `Action`;
- a identidade do solicitante acompanha a operação de ponta a ponta;
- segredos trafegam somente por referência;
- a credencial de escrita pertence exclusivamente ao Executor.

# 56. Proteções de carga e estabilidade

O loop corrige continuamente a realidade. Sem limites, ele pode sobrecarregar o provider ou disputar indefinidamente com outro agente.

- **Limite de taxa e backpressure:** o Executor limita a concorrência e a taxa de chamadas ao provider e respeita sinais de limite do provider (por exemplo, `Retry-After`).
- **Flapping:** quando o mesmo recurso diverge repetidamente após convergir, o Manager registra a condition `DriftLoop` e o Reconciler aplica backoff crescente até intervenção, em vez de corrigir indefinidamente.
- **Restart em massa:** jitter na reconciliação inicial e periódica, e limite de mensagens pendentes por consumidor.
- **Métricas mínimas:** latência até a convergência, idade da última reconciliação por recurso, idade do último `observed`, quantidade de `action` pendentes e taxa de falha por provider (ver `NATS.md`, observabilidade).
- **Pontos únicos de falha:** Manager, PostgreSQL e mensageria são dependências críticas. Com o Manager indisponível, o loop continua para o `desired` já publicado, mas não aceita novos pedidos nem atualiza o SSOT.

# 57. Propriedades desejadas

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

# 58. Checklist de implementação

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

### Observer

- [ ] É read-only?
- [ ] Consegue observar a realidade?
- [ ] Publica `observed`?
- [ ] Executa periodicamente?
- [ ] Informa `observedAt`?
- [ ] Distingue `present`, `absent` e `unknown`?

### Reconciler

- [ ] Consome `desired`?
- [ ] Consome `observed`?
- [ ] Compara os dois estados?
- [ ] Pode ser acionado por qualquer alteração?
- [ ] Reavalia periodicamente?
- [ ] Só decide com `desired` e `observed` conclusivos e dentro do limite de validade?
- [ ] Não reemite `action` pendente?
- [ ] A comparação entre `desired` e `observed` está definida para o recurso?
- [ ] Produz `action`?
- [ ] Não executa a ação diretamente?

### Executor

- [ ] Consome `action`?
- [ ] Possui somente os privilégios necessários?
- [ ] Revalida a `action` contra o `desired` vigente?
- [ ] Deduplica por `actionId`?
- [ ] Possui chave de correlação com o recurso externo?
- [ ] Limita taxa e concorrência contra o provider?
- [ ] Executa operações de forma idempotente?
- [ ] Publica `completed` ou `failed`?
- [ ] Não decide o estado desejado?

### Messaging

- [ ] Subject segue a gramática oficial?
- [ ] `messageType` é válido?
- [ ] `operation` é semanticamente preciso?
- [ ] `messageId` é único?
- [ ] `correlationId` é utilizado quando necessário?
- [ ] `causationId` é utilizado quando necessário?
- [ ] Reentrega é suportada?
- [ ] Ordering é explicitamente definido quando necessário?

# 59. Fonte de verdade

Este documento define o **Resource Control Loop** como padrão arquitetural da plataforma.

`MESSAGING.md` define a semântica das mensagens.

`NATS.md` define a implementação da mensageria utilizando NATS e NATS JetStream.

`SCHEMA.md` define os contratos formais e a evolução dos schemas.

`RESOURCE-CONTROL-SECURITY.md` define os requisitos de segurança do padrão.

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