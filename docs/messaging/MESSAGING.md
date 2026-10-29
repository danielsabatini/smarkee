# Modelo Semântico de Mensageria

# 1. Introdução

Este documento define o modelo semântico oficial para comunicação assíncrona entre componentes da plataforma.

O modelo é independente do mecanismo de transporte e deve permanecer válido mesmo quando a tecnologia de mensageria for substituída.

A implementação de referência em NATS e NATS JetStream é definida separadamente em `NATS.md` (decisão 0101).

Este documento é a fonte de verdade para:

- semântica das mensagens;
- tipos de mensagens;
- endereçamento lógico;
- identificação do emissor;
- identificação do recurso;
- operações associadas;
- envelope das mensagens;
- idempotência;
- ordenação;
- correlação;
- evolução de contratos;
- responsabilidades entre aplicação e transporte.

# 2. Objetivos

O objetivo é estabelecer um modelo consistente, explícito, idempotente e evolutivo para comunicação assíncrona.

O modelo deve:

- representar estado desejado (`desired`) e fatos consolidados (`updated`);
- permitir endereçamento lógico por tipo de mensagem, módulo e recurso;
- permitir múltiplos consumidores independentes;
- suportar diferentes padrões de entrega;
- permitir implementação em diferentes mecanismos de mensageria;
- suportar reentrega, retry e replay;
- permitir evolução controlada dos contratos;
- preservar a separação entre domínio e tecnologia de transporte.

# 3. Princípios

## 3.1 Semântica antes do transporte

O contrato deve permanecer válido mesmo que o mecanismo de mensageria seja substituído.

Uma abstração própria do broker é uma implementação, não uma definição de domínio.

Exemplos de conceitos que não pertencem ao modelo semântico:

```text
JetStream Consumer
Kafka Partition
RabbitMQ Exchange
Kafka Offset
NATS Stream
```

Esses conceitos pertencem à implementação do transporte.

## 3.2 Emissor explícito no envelope

A identidade semântica de uma mensagem declara quem a produziu (`emitter` no envelope).

O destinatário não faz parte do endereço nem da identidade da mensagem.

A distinção é deliberada:

```text
emitter   = quem decidiu e produziu a mensagem (declarado no envelope)
consumer  = quem possui interesse na mensagem (manifestado por subscription)
```

O interesse do consumidor é expresso por subscription, consumer, grupo de consumidores, filtro, binding ou mecanismo equivalente do transporte.

Exemplo de endereço (Subject):

```text
desired.ipm.organization.<resourceId>
```

O subject não afirma que a mensagem é destinada exclusivamente a um determinado consumidor.

## 3.3 Tipos semânticos explícitos

Cada mensagem deve declarar claramente **o que ela representa**.

O modelo utiliza duas classes fundamentais de mensagens no transporte assíncrono (decisão 0101):

```text
desired
updated
```

- `desired`: o estado pretendido pelo sistema, admitido e persistido pela API (ou suspenso pelo Controller);
- `updated`: o fato consolidado de convergência, alteração ou remoção confirmado pelo Controller.

A observação da realidade e a execução de ações não são mensagens no barramento: ocorrem em um ciclo atômico local do Controller sob bloqueio do SSOT (`RESOURCE-CONTROL-LOOP.md` §3.3; decisão 0096).

## 3.4 `desired` e fatos consolidados

O modelo possui dois momentos semânticos fundamentais:

- `desired`: intenção pretendida pela plataforma;
- `updated`: confirmação de que o recurso foi convergido, alterado ou removido pelo controlador.

`desired` não é um comando imperativo. Ele expressa o que deve existir.

`updated` não é uma simples confirmação de transporte: é o registro factual de que a reconciliação convergiu ou progrediu, contendo `desiredGeneration` e `observedGeneration`.

## 3.5 Declarativo sobre imperativo

Sempre que o problema puder ser modelado como estado, representar o estado desejado em vez de uma sequência de comandos.

Preferir:

```text
desired.ipm.organization.<organizationId>
```

quando a mensagem representa o estado desejado para uma Organization.

A operação concreta necessária para alcançar esse estado é responsabilidade do Controller no seu ciclo de reconciliação.

Não transformar o endereço de mensageria em uma API RPC imperativa.

## 3.6 Explícito sobre implícito

Usar nomes que expressem o significado do campo.

Preferir:

```text
messageId
resourceId
resourceType
messageType
schemaVersion
desiredGeneration
observedGeneration
occurredAt
publishedAt
correlationId
causationId
```

Evitar:

```text
id
type
version
state
timestamp
```

quando o significado não for inequívoco.

## 3.7 Separação entre identidade da mensagem e identidade do recurso

`messageId` identifica uma mensagem.

`resourceId` identifica um recurso.

Eles nunca devem ser tratados como equivalentes.

```text
messageId  != resourceId
```

## 3.8 Idempotência como requisito

Consumidores de mensagens persistentes devem ser capazes de processar a mesma mensagem mais de uma vez sem corromper o estado ou produzir efeitos cumulativos indevidos.

Não utilizar exatamente-uma-entrega como requisito arquitetural da aplicação.

## 3.9 Falhas são normais

O modelo assume que podem ocorrer:

- duplicação;
- reentrega;
- atraso;
- indisponibilidade temporária;
- reinício do produtor;
- reinício do consumidor;
- perda de conectividade;
- mensagens fora da ordem global.

A aplicação deve permanecer correta sob essas condições.

# 4. Modelo conceitual

O ciclo declarativo é:

```mermaid\ngraph LR
    A[API: Admissão Síncrona] -->|grava no SSOT e outbox| B[(SSOT)]
    B -->|Publisher entrega| C[Stream DESIRED]
    C -->|Informer| D[Controller]
    D <-->|observa, decide, age, reobserva| E[External System]
    D -->|grava convergência e outbox| B
    B -->|Publisher entrega| F[Stream UPDATED]
```

A mensageria transporta as intenções e os fatos consolidados desse ciclo:

```text
Cliente
    ↓ HTTP (síncrono: 201/200/202 com o Resource)
API
    ↓ (uma transação: recurso + desired no outbox)
Publisher
    ↓
DESIRED (NATS)
    ↓
Controller (Informer / Workqueue)
    ↓ (ciclo atômico: observa, decide, age, reobserva sob FOR UPDATE)
SSOT (observed, phase, conditions, observedGeneration) + outbox (updated)
    ↓
Publisher
    ↓
UPDATED (NATS)
```

A aceitação da publicação não significa que o recurso convergiu.

A convergência depende da reobservação no sistema externo compatível com o estado desejado, consolidada pelo Controller no SSOT e anunciada no `updated`.

# 5. Tipos de mensagem

O barramento assíncrono transporta estritamente duas mensagens oficiais (decisão 0101): `desired` e `updated`.

## 5.1 `desired`

Representa o estado desejado estabelecido no SSOT pela API na admissão (ou atualizado pelo Controller para suspender a reconciliação).

Exemplo de Subject:

```text
desired.ipm.organization.<organizationId>
```

Características:

- declarativo;
- versionado por `desiredGeneration`;
- idempotente;
- independente de uma sequência específica de comandos;
- suficientemente completo para que o Controller e as projeções determinem o delta necessário;
- uma mensagem de **estado**: o `desired` mais recente do recurso (maior `desiredGeneration`) substitui os anteriores. O Subject segue o padrão de 4 tokens `<messageType>.<module>.<resourceType>.<resourceId>`;
- no envelope, a operação associada é sempre `changed`.

## 5.2 `updated`

Representa uma alteração consolidada no recurso ou no seu estado persistido, emitida pelo Controller ao concluir um ciclo de reconciliação (ou pela API em recursos de perfil `internal-state`).

Exemplo de Subject:

```text
updated.ipm.organization.<organizationId>
```

Características:

- factual e consolidado;
- útil para consumidores interessados em projeções, console, auditoria e métricas;
- o `data` do `updated` traz `desiredGeneration` e `observedGeneration` (decisão 0072, modelo do Kubernetes). Iguais, com `phase = Ready`: a geração convergiu. `observedGeneration` menor: a alteração está em andamento. `observedGeneration` nunca é maior que `desiredGeneration`;
- quando o recurso é excluído após a confirmação da ausência no sistema externo, o `updated` anuncia o fato com `removed = true`;
- no envelope, a operação associada é sempre `changed`.

## 5.3 O que aconteceu com os tipos de mensagens legados

Na arquitetura anterior (loop de 7 papéis, descontinuada pelas decisões 0096, 0098 e 0101), mensagens intermediárias trafegavam no broker:

| Tipo legado | Destino na arquitetura atual | Motivo da mudança |
|---|---|---|
| `requested` | Substituído pela **admissão síncrona da API** (`RESOURCE-CONTROL-LOOP.md` §6.1). A API valida, grava o recurso e o `desired` no outbox e responde imediatamente `201`/`200`/`202` com o `Resource`. | Elimina a fila de entrada assíncrona e a entidade `Operation` (decisão 0098). |
| `observed` | A observação é realizada **diretamente pelo Controller** contra o provedor externo e persistida no SSOT em `observed` (com `presence` e `observedAt`). | Elimina leituras obsoletas e corridas entre Observer e Reconciler (decisão 0096). |
| `action`, `completed`, `failed` | A decisão (`decide`) e a ação executada são **etapas locais e atômicas** do ciclo do Controller. | Ação e observação ocorrem no mesmo ciclo sob bloqueio da linha no SSOT, eliminando comandos operacionais e `actionId` no transporte. |

## 5.4 Classes de mensagem

As duas mensagens do transporte pertencem a classes bem definidas:

| Classe | Tipo | Característica | Padrão de Entrega e Retenção |
|---|---|---|---|
| **Estado** | `desired` | A mais recente por recurso substitui as anteriores e deve estar disponível para o Informer e após restart. | Fanout, com retenção do último estado por recurso (`max_msgs_per_subject: 1` no Stream `DESIRED`). |
| **Fato** | `updated` | Registro imutável de convergência ou remoção, consumido por vários consumidores independentes. | Fanout, com retenção temporal (`max_msgs_per_subject: 1` no Stream `UPDATED`). |
| **Auditoria** | agregada (`audit.>`) | Histórico cumulativo e imutável de todas as mensagens `desired` e `updated`. | Stream `AUDIT` alimentado por Stream Sources de `DESIRED` e `UPDATED`, com `deny_delete: true`. |

Mensagens utilizam sempre a operação `changed` no envelope, de modo que cada recurso possua um único Subject por tipo de mensagem (`NATS.md`).

# 6. Endereçamento lógico

O endereço lógico canônico no transporte (Subject) é estritamente estruturado em **4 tokens** (decisão 0101):

```text
<messageType>.<module>.<resourceType>.<resourceId>
```

Exemplo:

```text
desired.ipm.organization.0199c8a4
```

A representação acima é uma convenção lógica legível.

Um transporte pode representá-la como:

- subject;
- topic;
- routing key;
- destination;
- headers;
- combinação desses mecanismos.

## 6.1 `emitter`

Identifica o componente funcional que autorizou e produziu a decisão da mensagem. Ele é declarado **exclusivamente no envelope** (`schemas/common/message-envelope.v1.schema.json`) e não faz parte dos tokens do Subject.

Valores permitidos no envelope:

```text
api
controller
```

- **`api`:** produz o `desired` durante a admissão síncrona de uma escrita do cliente;
- **`controller`:** produz o `updated` ao concluir o ciclo de reconciliação, ou um `desired` suspenso (`reconciliation = suspended`) ao atingir o limite de falhas.

O emissor representa a **autoridade que decidiu**, e não o processo que a transportou. A entrega física do outbox ao broker é realizada pelo **Publisher** (`RESOURCE-CONTROL-LOOP.md` §6.6), que é identificado no campo `publishedBy` do envelope e na identidade de conexão NATS.

## 6.2 `messageType`

Identifica o significado semântico da mensagem. No transporte:

```text
desired
updated
```

## 6.3 `module`

Identifica o módulo funcional da plataforma ao qual a mensagem pertence.

Exemplos:

```text
core
ipm
bsm
sum
agent
runner
tool
```

`core` é o módulo dos recursos da própria plataforma que existem antes de qualquer Organization, como a Account. `ipm` é o módulo de identidade e contém a Organization, Service Account, User, Permission, Role e Group (decisão 0016). `bsm` contém cobrança e faturamento, e `sum` gerencia o uso e catálogo de serviços.

## 6.4 `resourceType`

Identifica o tipo de recurso.

Exemplos:

```text
organization
account
serviceaccount
user
permission
role
group
service
agent
runner
```

O `resourceType` deve utilizar a terminologia oficial do domínio em singular ou conforme o contrato do recurso.

## 6.5 `resourceId`

Identifica o recurso de forma inequívoca e estável.

Regras:

- deve ser estável durante todo o ciclo de vida do recurso;
- deve ser opaco;
- não deve carregar significado de negócio mutável;
- não deve ser confundido com `messageId`;
- não deve ser substituído pelo nome amigável do recurso;
- não deve conter caracteres que interfiram no transporte (como `.` no NATS).

UUIDv7 é o padrão adotado para `resourceId`.

## 6.6 `operation`

No envelope da mensagem, o campo `operation` representa a operação associada. Para mensagens de estado e fatos consolidados no transporte (`desired` e `updated`), a operação é **sempre fixada como `changed`**:

```text
changed
```

A decisão sobre se a realidade exige criação, atualização ou exclusão decorre da comparação de estado (`desired` vs `observed`) realizada internamente pelo Controller, e não de um verbo imperativo de transporte.

# 7. Exemplo do fluxo completo

Fluxo canônico para o ciclo de vida de uma Organization (`ipm/organization`):

```text
1. Cliente envia POST /v1/ipm/organizations
2. API valida síncrona, persiste o recurso no SSOT (phase: Pending) e grava no outbox:
   Subject: desired.ipm.organization.<id> (emitter: api, desiredGeneration: 1)
   API responde síncrono 201 Created com o Resource.
3. Publisher entrega a linha do outbox ao NATS (Stream DESIRED) e marca published_at.
4. Controller consome desired via Informer, enfileira na Workqueue e inicia o ciclo:
   - Bloqueia a linha no SSOT (FOR UPDATE).
   - Observa o Zitadel (GET organization): ausente (presence: absent).
   - decide(desired, observed) -> create (reason: resource_absent).
   - Age no Zitadel (POST organization): sucesso.
   - Reobserva no Zitadel (GET organization): presente (presence: present).
   - Convergência confirmada: grava phase: Ready, observedGeneration: 1 no SSOT.
   - Grava outbox do updated na mesma transação:
     Subject: updated.ipm.organization.<id> (emitter: controller)
5. Publisher entrega o updated ao NATS (Stream UPDATED).
6. Console, auditoria e projeções consomem updated.
```

# 8. Destinatários e consumidores

O modelo não define destinatários no Subject nem no envelope.

Exemplo:

```text
desired.ipm.organization.<id>
```

Pode ser consumido simultaneamente e de forma independente por:

```text
controller (Informer do tipo ipm/organization)
projeções locais de outros tipos (ex: ipm/user, bsm/account)
auditoria (Stream AUDIT)
```

O produtor (`api` ou `controller`) não conhece os consumidores. Novos consumidores podem ser adicionados sem alterar o produtor nem os contratos de emissão.

# 9. Envelope da mensagem

Toda mensagem persistente possui um envelope explícito definido pelo contrato canônico (`schemas/common/message-envelope.v1.schema.json`).

Estrutura de `desired`:

```json
{
  "messageId": "0199c8c0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "api",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "requestedBy": "0199c8a0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "correlationId": "0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "causationId": null,
  "occurredAt": "2026-10-28T12:00:00Z",
  "publishedAt": "2026-10-28T12:00:01Z",
  "publishedBy": "ipm-organization-publisher",
  "data": {
    "lifecycle": "present",
    "reconciliation": "active",
    "resourceName": "acme",
    "displayName": "ACME Corp"
  }
}
```

Estrutura de `updated`:

```json
{
  "messageId": "0199c920-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "schemaVersion": "1.0",
  "messageType": "updated",
  "emitter": "controller",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "observedGeneration": 1,
  "requestedBy": "0199c8a0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "correlationId": "0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "causationId": "0199c8c0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "occurredAt": "2026-10-28T12:00:05Z",
  "publishedAt": "2026-10-28T12:00:06Z",
  "publishedBy": "ipm-organization-publisher",
  "data": {
    "phase": "Ready",
    "presence": "present",
    "resourceName": "acme",
    "displayName": "ACME Corp",
    "conditions": [
      {
        "type": "Ready",
        "status": "True",
        "reason": "Reconciled",
        "observedGeneration": 1,
        "lastTransitionAt": "2026-10-28T12:00:05Z"
      }
    ]
  }
}
```

# 10. Campos do envelope

| Campo | Obrigatório | Aplicação | Definição |
|---|---:|---|---|
| `messageId` | Sim | Todos | Identidade única da mensagem (UUIDv7); chave de deduplicação no transporte |
| `schemaVersion` | Sim | Todos | Versão do contrato da mensagem (`1.0`) |
| `messageType` | Sim | Todos | Tipo semântico da mensagem (`desired` ou `updated`) |
| `emitter` | Sim | Todos | Emissor lógico decisor (`api` ou `controller`) |
| `module` | Sim | Todos | Módulo funcional (ex: `ipm`, `core`, `bsm`, `sum`) |
| `resourceType` | Sim | Todos | Tipo de recurso gerenciado |
| `resourceId` | Sim | Todos | Identificador estável do recurso |
| `operation` | Sim | Todos | Operação semântica associada (fixado como `changed`) |
| `desiredGeneration` | Sim | `desired` e `updated` | Geração lógica do estado desejado |
| `observedGeneration` | Condicional | `updated` | Última geração cuja convergência foi confirmada pelo Controller |
| `requestedBy` | Condicional | `desired` e `updated` | Identificador do solicitante original autenticado, ou `anonymous` nas escritas anônimas |
| `correlationId` | Recomendado | Todos | Identificador de rastreamento do fluxo lógico de ponta a ponta |
| `causationId` | Condicional | Mensagens derivadas | `messageId` da mensagem que originou a atual |
| `occurredAt` | Sim | Todos | Momento em que a alteração ou ciclo ocorreu no emissor |
| `publishedAt` | Sim | Todos | Momento em que a mensagem foi entregue ao broker pelo Publisher |
| `publishedBy` | Sim | `desired` e `updated` | Identidade de mensageria do Publisher que entregou a mensagem |
| `data` | Sim | Todos | Conteúdo específico e estruturado do recurso |

## 10.1 Regras dos campos de decisão e rastreabilidade

- **`requestedBy`:** identifica quem pediu a alteração, e não quem a executou. É definido pela API a partir do solicitante autenticado e propagado no `desired` e no `updated`. Não contém senhas nem credenciais. Nas escritas anônimas (`RESOURCE-CONTROL-LOOP.md` §6.1.2), o valor é o literal `anonymous`.
- **`publishedBy`:** identifica a identidade de mensageria que retirou a mensagem do outbox e a entregou ao broker (ex: `ipm-organization-publisher`). Permite distinguir quem decidiu (`emitter: api` ou `controller`) de quem transportou (`RESOURCE-CONTROL-LOOP.md` §6.6.2).
- **Sem `actionId` no transporte:** como as ações contra o sistema externo ocorrem em ciclo local do Controller (decisão 0096), não há mais identificadores de ações no envelope nem mensagens operacionais de transporte.

# 11. `schemaVersion`

Versiona o contrato estrutural e semântico da mensagem.

Não representa:

- versão do recurso;
- versão do estado desejado;
- versão da aplicação;
- versão do broker;
- `resourceVersion`.

Mudanças incompatíveis exigem estratégia explícita de versionamento e schema novo.

# 12. `desiredGeneration`

Representa a geração lógica do estado desejado.

Uma alteração material admitida em `desired` incrementa a geração:

```text
desiredGeneration = 1
        ↓
desiredGeneration = 2
        ↓
desiredGeneration = 3
```

A geração é propriedade do recurso no SSOT, não do transporte.

# 13. `observedGeneration`

Representa a última geração cuja convergência foi formalmente confirmada pelo Controller após reobservar o sistema externo.

Regras:

- `observedGeneration` só é avançado quando a reobservação factual comprovar que a realidade do sistema externo coincide plenamente com o `desired` daquela geração (`RESOURCE-CONTROL-LOOP.md` §36);
- `observedGeneration` nunca ultrapassa `desiredGeneration`;
- `observedGeneration == desiredGeneration` com `phase = Ready` significa que a alteração foi concluída com sucesso;
- em recursos de perfil `internal-state`, a admissão da API já grava `observedGeneration = desiredGeneration`.

# 14. `resourceVersion`

Quando o domínio utilizar controle otimista de concorrência, `resourceVersion` é manipulado no banco e nas interfaces HTTP (`RESOURCE-CONTROL-LOOP.md` §6.1.1).

`resourceVersion` é uma string opaca.

Não deve ser interpretado como:

- número sequencial;
- timestamp;
- geração;
- ordenação global.

Não substitui `desiredGeneration`, `observedGeneration` nem `messageId`.

# 15. `correlationId`

Relaciona mensagens e ações pertencentes ao mesmo fluxo lógico.

Exemplo:

```text
HTTP Request (API)
       │ (gera correlationId)
       ├── SSOT Resource (persiste correlation_id)
       │
       ├── desired (no outbox, com o mesmo correlationId)
       │
       └── updated (emitido pelo Controller, preservando o correlationId)
```

Todas compartilham:

```text
correlationId = 0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e
```

`correlationId` não substitui `messageId`.

# 16. `causationId`

Identifica a mensagem que causou diretamente a produção da mensagem atual.

Exemplo:

```text
desired (messageId: msg-001)
    ↓
updated (causationId: msg-001, messageId: msg-002)
```

Isso permite reconstruir a causalidade dos fatos sem transformar a mensageria em log imperativo.

# 17. Conteúdo de `data`

`data` pertence ao contrato específico do recurso e é validado pelo respectivo schema.

O contrato do recurso define:

- propriedades válidas;
- tipos;
- obrigatoriedade;
- mutabilidade;
- semântica e campos confidenciais;
- regras de normalização e comparação.

O payload não transporta segredos em texto puro (`RESOURCE-CONTROL-SECURITY.md`).

# 18. Presença e ausência de recursos

Sistemas declarativos representam a intenção de ausência de forma declarativa:

```json
{
  "messageType": "desired",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "organization-01",
  "operation": "changed",
  "desiredGeneration": 8,
  "data": {
    "lifecycle": "absent"
  }
}
```

O Controller observa a intenção (`lifecycle = absent`), executa a exclusão no sistema externo, reobserva até constatar `presence = absent` e, ao convergir, remove o registro do SSOT e emite o `updated` com `removed = true`.

# 19. Organization e contexto

A Organization é a unidade primária de isolamento da plataforma (`SCHEMA.md`). A Organization a que um recurso pertence faz parte do seu payload em `data.organizationId`.

Exemplo:

```json
{
  "data": {
    "organizationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "resourceName": "backend-runner"
  }
}
```

Não inserir o ID da Organization no Subject NATS. O roteamento no transporte é padronizado em 4 tokens (`<messageType>.<module>.<resourceType>.<resourceId>`).

# 20. Padrões de entrega

No modelo consolidado, a mensageria utiliza o padrão **Fanout** com persistência JetStream (`NATS.md`):

```mermaid\ngraph TD
    Desired[Stream DESIRED] --> Informer[Controller Informer]
    Desired --> Projections[Projeções Locais da API]
    Desired --> Audit[Stream AUDIT]

    Updated[Stream UPDATED] --> Console[Console]
    Updated --> Metrics[Métricas / Observabilidade]
    Updated --> Audit
```

- **`DESIRED` (`desired.>`):** retém a última mensagem por recurso (`max_msgs_per_subject: 1`), com entrega direta (`allow_direct: true`). Novos consumidores (e o Informer após reinício) recebem imediatamente o estado vigente;
- **`UPDATED` (`updated.>`):** retém os fatos consolidados de convergência (`max_msgs_per_subject: 1`), alimentando o Console e serviços de observabilidade;
- **`AUDIT` (`audit.>`):** consome de `DESIRED` e `UPDATED` via stream sources, acumulando histórico imutável com `deny_delete: true`.

# 21. Idempotência e deduplicação

A aplicação deve permanecer correta sob entregas duplicadas ou reprocessamento:

1. **No Transporte (NATS JetStream):** deduplicação transparente baseada no cabeçalho `Nats-Msg-Id` igual ao `messageId` do envelope;
2. **No Controller (Informer e Workqueue):** a Workqueue deduplica chaves de recursos pendentes; ciclos subsequentes leem a linha no SSOT sob `FOR UPDATE` e reobservam a realidade factual do sistema externo;
3. **No Banco de Dados (SSOT):** padrão Transactional Outbox com controle otimista de versão (`resourceVersion`) e travas consultivas por recurso.

# 22. Ordenação

A unidade de ordenação é estritamente o recurso (`resourceId`). Não existe pressuposto de ordenação global entre recursos distintos.

Para o mesmo recurso:

- a mensagem mais recente de `desired` é identificada por `desiredGeneration`;
- a confirmação de convergência no `updated` é identificada por `observedGeneration`;
- o Publisher garante entrega em ordem sequencial a partir do outbox do SSOT.

# 23. Retry, quarentena e replay

Falhas de transporte e processamento obedecem a regras explícitas:

- falhas transitórias de conexão são tratadas por retry automático com backoff exponencial;
- falhas de reconciliação no Controller incrementam `failure_count` até o `failure_limit` (padrão 5 tentativas), momento em que a reconciliação é suspensa no SSOT e anunciada no `desired` (`reconciliation = suspended`);
- mensagens malformadas que violem schemas estruturais são rejeitadas e isoladas em quarentena sem bloquear o stream (`NATS.md`).

# 24. Falha após a escrita externa

Um dos cenários críticos de controle ocorre quando o Controller executa uma escrita com sucesso no sistema externo (ex: cria a organização no Zitadel), mas cai antes de comitar a transação no SSOT:

```mermaid\nsequenceDiagram
    participant C as Controller
    participant X as Zitadel (Externo)
    participant S as SSOT

    C->>X: POST organization
    X-->>C: 201 Created
    Note over C: Falha de energia ou reinício antes do COMMIT

    Note over C: Novo ciclo (Informer reentrega ou reavaliação periódica)
    C->>S: BEGIN; FOR UPDATE
    C->>X: GET organization (observa)
    X-->>C: 200 OK (presente)
    C->>C: decide -> convergido (nenhuma ação necessária)
    C->>S: grava Ready, observedGeneration e updated no outbox; COMMIT
```

Como o Controller sempre **observa a realidade antes de decidir**, o ciclo seguinte constata que o recurso já existe, evita uma escrita duplicada e converge com sucesso. Não é necessário mecanismo de two-phase commit distribuído.

# 25. Transação entre mensageria e banco (Transactional Outbox)

Não há transação distribuída entre banco e mensageria.

A consistência é garantida pelo padrão **Transactional Outbox**:

```text
API ou Controller (uma transação local):
    BEGIN
        atualiza linha do recurso no SSOT
        insere linha correspondente no <tipo>_outbox
    COMMIT
```

Fora da transação, o processo **Publisher** do componente:

```text
Publisher:
    lê linhas pendentes no outbox em ordem
    publica no NATS com confirmação (JetStream ACK)
    marca published_at na linha do outbox
```

Isso garante que um estado nunca seja anunciado no broker sem estar persistido no SSOT, e que nenhuma alteração persistida deixe de ser entregue.

# 26. Evolução de contratos

Mudanças de contrato devem preservar consumidores existentes quando compatível.

Regras:

- adicionar campos opcionais no payload `data` é preferível a alterar campos existentes;
- nunca reutilizar um campo para outro significado;
- mudanças incompatíveis exigem estratégia explícita de versionamento em `schemaVersion`;
- consumidores devem ignorar extensões desconhecidas quando o formato permitir;
- `messageType` é um conjunto estritamente controlado (`desired`, `updated`);
- `operation` no envelope é sempre fixado como `changed`.

# 27. Segurança

Mensagens devem conter apenas os dados estritamente necessários para a reconciliação e consumo.

Não transportar:

- senhas ou hashes de senhas;
- tokens de acesso ou refresh tokens;
- chaves privadas ou certificados;
- credenciais de contas de serviço.

Segredos trafegam exclusivamente por referência segura (`RESOURCE-CONTROL-SECURITY.md`).

A credencial de escrita contra o sistema externo pertence exclusivamente ao Controller. A API não possui credencial do provedor externo, e o Publisher possui apenas permissão de publicação nos subjects do seu respectivo tipo no NATS.

# 28. Observabilidade

A publicação e o consumo são observáveis por métricas e logs estruturados OpenTelemetry.

Métricas mínimas recomendadas:

```text
messages_published_total
messages_consumed_total
messages_failed_total
outbox_pending_count
outbox_oldest_age_seconds
processing_duration_seconds
publish_duration_seconds
consumer_lag
redelivery_count
```

Logs e traces correlacionam os seguintes atributos semânticos:

```text
messageId
correlationId
causationId
emitter
module
resourceType
resourceId
messageType
operation
desiredGeneration
observedGeneration
```

# 29. Naming

Os nomes e tokens devem ser:

- explícitos;
- estáveis;
- semanticamente precisos;
- livres de abreviações desnecessárias;
- estritamente em minúsculas (lowercase).

Exemplo correto:

```text
desired.ipm.organization.0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e
```

Não utilizar:

```text
Desired.IPM.Organization.0199c8a4...
```

# 30. Restrições do transporte

O modelo semântico deve ser independente de broker, mas deve respeitar as restrições físicas de transporte:

- **Separador de tokens:** no NATS, o ponto (`.`) é o separador canônico de tokens. Portanto, o `resourceId` não deve conter pontos (`.`);
- **Tamanho máximo de mensagem:** o payload `data` é limitado a 256 KiB; mensagens completas no envelope são limitadas a 512 KiB no NATS JetStream (`NATS.md`);
- **Wildcards:** tokens coringa (`*` e `>`) são reservados para assinaturas de consumidores e nunca devem ser utilizados como identificadores de recursos.

# 31. Anti-padrões

## 31.1 Tratar `desired` como comando imperativo

Evitar pensar em `desired` como uma ordem de criação ou deleção. `desired` representa o estado final que a plataforma deve alcançar.

## 31.2 Tratar ACK de transporte como convergência

Receber confirmação de publicação (ACK do NATS) indica apenas que o broker gravou a mensagem no Stream. A convergência real do recurso só é atestada quando o Controller confirma o estado no `updated`.

## 31.3 Colocar destinatário no Subject

Evitar:

```text
controller.desired.ipm.organization.<id>
```

O Subject canônico expressa o fato (`desired.ipm.organization.<id>`), e os interessados manifestam intenção via subscription.

## 31.4 Colocar o emissor no Subject

Evitar Subjects de 5 ou 6 tokens contendo o prefixo do emissor. O emissor (`api` ou `controller`) pertence ao campo `emitter` do envelope.

## 31.5 Depender de ordenação global

Não assumir que mensagens de recursos diferentes estejam ordenadas globalmente. A ordenação é estritamente garantida por `resourceId`.

## 31.6 Colocar segredos no payload

Nunca transportar credenciais ou segredos em texto puro no envelope ou em `data`.

## 31.7 Criar um novo `messageType` para cada operação

Evitar criar tipos como `organization-created` ou `organization-deleted`. O estado pretendido é sempre `desired`, e a confirmação é sempre `updated`.

# 32. Exemplos completos

## 32.1 API estabelece Desired na admissão

Subject:

```text
desired.ipm.organization.0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e
```

Envelope:

```json
{
  "messageId": "0199c8c0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "api",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "requestedBy": "0199c8a0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "correlationId": "0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "occurredAt": "2026-10-28T12:00:00Z",
  "publishedAt": "2026-10-28T12:00:01Z",
  "publishedBy": "ipm-organization-publisher",
  "data": {
    "lifecycle": "present",
    "reconciliation": "active",
    "resourceName": "acme",
    "displayName": "ACME Corp"
  }
}
```

## 32.2 Controller publica alteração consolidada (Updated)

Subject:

```text
updated.ipm.organization.0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e
```

Envelope:

```json
{
  "messageId": "0199c920-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "schemaVersion": "1.0",
  "messageType": "updated",
  "emitter": "controller",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "observedGeneration": 1,
  "requestedBy": "0199c8a0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "correlationId": "0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "causationId": "0199c8c0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "occurredAt": "2026-10-28T12:00:05Z",
  "publishedAt": "2026-10-28T12:00:06Z",
  "publishedBy": "ipm-organization-publisher",
  "data": {
    "phase": "Ready",
    "presence": "present",
    "resourceName": "acme",
    "displayName": "ACME Corp",
    "conditions": [
      {
        "type": "Ready",
        "status": "True",
        "reason": "Reconciled",
        "observedGeneration": 1,
        "lastTransitionAt": "2026-10-28T12:00:05Z"
      }
    ]
  }
}
```

## 32.3 Controller suspende reconciliação por limite de falhas

Quando a reconciliação falha repetidamente (`failure_count >= failure_limit`), o Controller marca o recurso como `Failed`, suspende a reconciliação e publica um `desired` atualizado:

Subject:

```text
desired.ipm.organization.0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e
```

Envelope:

```json
{
  "messageId": "0199c980-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "controller",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 1,
  "requestedBy": "0199c8a0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "correlationId": "0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "occurredAt": "2026-10-28T12:05:00Z",
  "publishedAt": "2026-10-28T12:05:01Z",
  "publishedBy": "ipm-organization-publisher",
  "data": {
    "lifecycle": "present",
    "reconciliation": "suspended",
    "resourceName": "acme",
    "displayName": "ACME Corp"
  }
}
```

## 32.4 Controller confirma remoção convergida

Quando um recurso com `lifecycle = absent` é fisicamente excluído no sistema externo, o Controller apaga o registro do SSOT e publica o `updated` de desfecho:

Subject:

```text
updated.ipm.organization.0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e
```

Envelope:

```json
{
  "messageId": "0199c990-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "schemaVersion": "1.0",
  "messageType": "updated",
  "emitter": "controller",
  "module": "ipm",
  "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "operation": "changed",
  "desiredGeneration": 2,
  "observedGeneration": 2,
  "requestedBy": "0199c8a0-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "correlationId": "0199c8b2-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
  "occurredAt": "2026-10-28T12:10:00Z",
  "publishedAt": "2026-10-28T12:10:01Z",
  "publishedBy": "ipm-organization-publisher",
  "data": {
    "phase": "Deleting",
    "presence": "absent",
    "removed": true
  }
}
```

# 33. Matriz semântica

| `messageType` | Significado | Emissor típico (`emitter`) | Operação típica (`operation`) | Stream NATS JetStream |
|---|---|---|---|---|
| **`desired`** | Estado pretendido (intenção declarativa) | `api` (admissão) ou `controller` (suspensão) | `changed` | `DESIRED` |
| **`updated`** | Fato consolidado (convergência, transição ou remoção) | `controller` (ou `api` em `internal-state`) | `changed` | `UPDATED` |

# 34. Matriz `desired` × `updated`

| Dimensão | `desired` | `updated` |
|---|---|---|
| **Significado** | Estado pretendido pela plataforma | Estado consolidado e confirmado |
| **Natureza** | Declarativa (intenção) | Factual (realidade observada e convergida) |
| **Classe de Mensagem** | Estado | Fato |
| **Operação no Envelope** | `changed` | `changed` |
| **Substituição de Mensagem** | O `desired` de maior geração substitui o anterior | O `updated` mais recente reflete o estado atual |
| **Emissor (`emitter`)** | `api` (admissão) ou `controller` (ao suspender) | `controller` |
| **Geração Relevante** | `desiredGeneration` | `desiredGeneration` e `observedGeneration` |
| **Consumidores Típicos** | Controller (Informer), Projeções de outros módulos | Console, Observabilidade, Auditoria, Métricas |
| **Stream JetStream** | `DESIRED` (`desired.>`) | `UPDATED` (`updated.>`) |

# 35. Responsabilidades por camada

| Camada | Papel | Responsabilidade |
|---|---|---|
| **API** | `api` | Admissão HTTP síncrona, validação, persistência inicial no SSOT e inserção do `desired` no outbox (`emitter: api`). |
| **Publisher** | `publisher` | Varredura do outbox transacional, publicação assíncrona com confirmação no NATS e atualização de `published_at` (`publishedBy`). |
| **Controller** | `controller` | Informer sobre `DESIRED`, Workqueue, ciclo atômico de reconciliação (observa, decide, age, reobserva), persistência da convergência e inserção do `updated` no outbox (`emitter: controller`). |
| **Transporte** | NATS / JetStream | Persistência nos streams `DESIRED`, `UPDATED` e `AUDIT`, deduplicação por `messageId`, entrega direta e distribuição de eventos. |

# 36. Critérios de conformidade

Uma implementação está conforme quando:

- utiliza estritamente o formato de Subject em 4 tokens: `<messageType>.<module>.<resourceType>.<resourceId>`;
- restringe `messageType` a `desired` ou `updated`;
- declara o emissor exclusivamente no envelope (`emitter: api` ou `controller`);
- utiliza sempre a operação `changed` no envelope;
- identifica a entrega pelo Publisher em `publishedBy`;
- não embute destinatário no Subject nem no envelope;
- separa `messageId` de `resourceId`;
- garante que `resourceId` não contenha pontos (`.`);
- utiliza `desiredGeneration` e `observedGeneration` de acordo com a semântica de convergência declarativa;
- utiliza outbox transacional para evitar escrita dupla entre banco e mensageria;
- suporta reentrega de mensagens sem efeitos cumulativos indesejados.

# 37. Fonte de verdade

Este documento é a fonte de verdade para a **semântica de mensageria** da plataforma.

A gramática oficial de endereçamento NATS (decisão 0101) é:

```text
<messageType>.<module>.<resourceType>.<resourceId>
```

A implementação concreta em NATS e JetStream é definida em `NATS.md`.
