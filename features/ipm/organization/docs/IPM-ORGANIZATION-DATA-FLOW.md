# ipm.organization: fluxo de dados (do `POST` até a organização no Zitadel)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/core/account/docs/CORE-ACCOUNT-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose), verificados
pela suíte e2e (`tests/e2e`) contra o Zitadel real, inclusive com falha de componente. A decisão de desenho é a
[0038](../../../../.decisions/0038-organization-refeita-a-partir-do-user.md); o loop unificado no Controller é a
[0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md), que substituiu o Observer, o Reconciler e o
Executor deste tipo.

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, dono)
são fictícios.

**Comando.** `sk ipm organization create|get|list|update|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

Criar uma Organization (`POST /v1/ipm/organizations {"name": "acme"}`) não cria nada no Zitadel diretamente. O pedido vira
uma mensagem `requested`, o Manager decide e grava, o Publisher publica o `desired`, e o Controller observa o Zitadel, decide,
escreve a organização, reobserva e grava o resultado.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/ipm/organizations` (via gateway) | `{name}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `ipm.organization`, `ipm.organization_operation`, `ipm.organization_outbox` |
| 4 | Publisher → Controller | NATS, Stream `DESIRED` | `desired` | `ipm.organization_outbox.published_at` |
| 5 | Controller → Zitadel; Controller → banco | HTTP no Zitadel; SQL, uma transação | (nada publicado) | a organização e o preparo para os usuários no Zitadel; `ipm.organization` (observado, fase, conditions), `ipm.organization_operation` → `completed`, `ipm.organization_outbox` |
| 6 | Publisher → consumidores | NATS, Stream `UPDATED` | `updated` (a cada mudança de fase) | `ipm.organization_outbox.published_at` |

Só o **Manager** admite pedidos e escreve o `desired` no SSOT de `ipm.organization`; só o **Controller** escreve o estado observado, a
fase, as conditions e a conclusão das Operations (e remove a linha quando a remoção converge). Receiver e Publisher não gravam nas
tabelas de recurso (o Publisher só marca `published_at` no outbox). O tipo só usa os Streams `REQUESTED` e `DESIRED` (mais
`UPDATED`, de saída): `OBSERVED`, `ACTION` e `RESULT` não existem para ele (decisão 0096).

Diagramas: criar [`flow/01-criar-organization.svg`](flow/01-criar-organization.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), atualizar e remover [`03`](flow/03-atualizar-e-remover.svg), falhas no Manager e na
mensageria [`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação [`05`](flow/05-falhas-na-reconciliacao.svg) e no
ação do provedor [`06`](flow/06-falhas-no-executor.svg). Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg).
Estados: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg).
Banco: [`database/01-er-fisico.svg`](database/01-er-fisico.svg).

> **Diagramas pendentes (decisão 0096):** os SVGs e os `.mmd` de `flow/`, `architecture/` e `database/` ainda mostram o modelo
> anterior, com Reconciler, Observer e Executor, os Streams `OBSERVED`, `ACTION` e `RESULT` e `organization_action_result`. O texto
> deste documento é o vigente.

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver | UUIDv7 minúsculo | Identidade da Organization. Vira o ID da organização no Zitadel (`organization_id`), então repetir a criação não duplica. |
| `operationId`, `requestDigest` | Receiver | UUIDv7 (ou determinístico com `Idempotency-Key`); SHA-256 do pedido | Identidade da Operation; a repetição produz o mesmo valor. |
| `ownerAccountId` | Receiver | `sub` do token | O dono. Vem do token, nunca do corpo, e vive só no `desired`. |
| `messageId` | Quem emite | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId`, `causationId` | Receiver; quem emite | UUIDv7; `messageId` da causa | Rastreiam o pedido do início ao fim e encadeiam causa e efeito. |

## 1. CLI → Receiver: `POST /v1/ipm/organizations`

O corpo é `{"name": "<nome>"}` (`schemas/ipm/organization/api-create-request`). O Receiver valida o token (audience
`roles-ipm`), exige a permissão `ipm.organization.create`, **o e-mail verificado** e a cota de Organizations por dono
(`IPM_ORGANIZATION_RECEIVER_API_ORGANIZATION_QUOTA`, padrão 1; o operador, com `ipm.organization.admin`, não tem cota), atribui o
`resourceId` e publica `requested` em `receiver.requested.ipm.organization.<resourceId>.create`, com `Nats-Msg-Id` igual ao
`operationId`:

```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e01", "schemaVersion": "1.0", "messageType": "requested",
  "emitter": "receiver", "module": "ipm", "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "create",
  "requestedBy": "0199c8a4-0000-7000-8000-00000000beef", "correlationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e02",
  "data": {
    "operationId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e9f", "requestDigest": "60303ae2…c752",
    "specification": {"name": "acme", "platformAccess": "granted"}, "ownerQuotaLimit": 1
  }
}
```

As demais rotas: `GET` e a lista (filtradas pelo dono, ou a Organization de que quem pede é usuário, reconhecido pelo Receiver do User; de outro dono é `404`, para não revelar que existe), `PATCH` (o dono
altera só o `name`; `platformAccess` e `reconciliation` são do operador), `DELETE?resourceVersion=` e
`GET .../operations/{operationId}`. Erros no formato `api-error`: `400` entrada inválida (sem repetir o valor enviado), `401`,
`403` (sem a permissão, e-mail não verificado, cota), `404`, `409` versão desatualizada, protegida ou ainda com usuários (`ResourcesAttached`, decisão 0077: o `DELETE` pergunta ao Receiver do User, com o token de quem pede), `422` reuso da `Idempotency-Key`, `503`
pedido não registrado (com `Retry-After`). Logo depois do `202`, a leitura pode dar `404` até o Manager gravar a Operation.
Diagrama: [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg). O contrato descritivo é `openapi.json`.

## 2. Manager consome `requested` e grava

O consumer durável `ipm-organization-manager-requested` (pull, ACK explícito) entrega a mensagem ao handler:

1. valida o envelope e os dados; desvio do contrato, de módulo ou de versão `MAJOR` é `TERM`;
2. aplica tudo numa transação, com a linha bloqueada e travas consultivas por nome e por dono;
3. ACK depois do `COMMIT`; falha transitória do banco é `RETRY` com atraso.

### 2.1 Decisão (domínio puro, `domain/organization.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar ou renomear | nome reservado (`core`, `smarkee`, `register`, `platform`, `system`, `admin`, `zitadel`) | recusa `validation` |
| criar ou renomear | nome já usado por outra Organization presente | recusa `validation` |
| criar | cota do dono esgotada (conferida de novo sob trava por dono; o Receiver só pré-checa) | recusa `validation` |
| atualizar ou remover | Organization inexistente ou já removida | recusa `not_found` |
| atualizar ou remover | `resourceVersion` diferente da atual | recusa `conflict` |
| remover | `deletionProtection` diferente de `false` (a Organization nasce protegida; registro sem o campo vale como protegido) | recusa `protected` (decisão 0043); antes dela, o Receiver já responde `409 DeletionProtected` |
| atualizar | só `deletionProtection` mudou (campo gerenciado, metadado `deletionProtection` da organização) | aceita como qualquer alteração (decisões 0072 e 0074): nova geração, fase `Reconciling`, Operation `accepted`; o Controller decide `update`, grava o metadado e a reobservação da nova geração conclui |
| qualquer | senão | aceita: `desired` com a nova geração (`lifecycle absent` ao remover) |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `ipm.organization` (geração 1, versão 1, fase `Pending`). A unicidade do nome e a cota são
  conferidas na mesma unidade atômica, sob trava consultiva (nome e dono), porque os índices de busca não são únicos.
- **Atualizar aceito:** `UPDATE` da linha (geração + 1, versão + 1, fase `Reconciling`). **Remover aceito:** `lifecycle =
  absent`, fase `Deleting`.
- **Operation:** `INSERT` em `ipm.organization_operation` com `accepted` (com a geração) ou `rejected` (com o motivo, sem geração).
- **Outbox:** só nas aceitas, `INSERT` em `ipm.organization_outbox` com a mensagem `desired`.

Reentrega com o mesmo `operationId` não grava nada (`Duplicate`, e o ACK acontece).

## 3. Outbox → NATS

O Publisher (`ipm-organization-publisher`) lê as linhas pendentes em ordem de `sequence`, valida o envelope de forma estrita,
acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.ipm.organization.<resourceId>.changed`, com
`Nats-Msg-Id` igual ao `messageId`; marca `published_at` **depois** da confirmação do transporte. Só uma instância publica
por vez (trava consultiva de sessão). Envelope inválido ou recusa permanente mantêm a mensagem pendente, registram `ERROR` e
tiram o Publisher de `ready`, sem derrubar o processo (decisão 0018). O `desired` publicado:

```json
{
  "messageType": "desired", "emitter": "manager", "module": "ipm", "resourceType": "organization",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "changed", "desiredGeneration": 1,
  "publishedBy": "ipm-organization-publisher",
  "data": {"name": "acme", "lifecycle": "present", "ownerAccountId": "0199c8a4-0000-7000-8000-00000000beef",
           "platformAccess": "granted", "reconciliation": "active"}
}
```

## 4. Controller (`ipm-organization-controller`)

Decisão 0096, no padrão do Kubernetes Controller (Informer + Workqueue, AGENTS.md §2.7). Um único processo observa o Zitadel,
decide, age e reobserva; a lógica está em `src/ipm_organization/controller/` (README do papel:
[`controller`](../src/ipm_organization/controller/README.md)).

### 4.1 Entrada: Informer, fila e reavaliação

- O **Informer** consome o Stream `DESIRED` (`manager.desired.ipm.organization.>`, consumer
  `ipm-organization-controller-desired-<instância>`) com barreira de sincronização inicial. A mensagem só avisa que o recurso
  mudou: o `resourceId` entra na **Workqueue**, e quem decide lê o `desired` no SSOT.
- A **Workqueue** deduplica por `resourceId` (várias mensagens da mesma Organization viram um só ciclo) e repete com *backoff*
  exponencial com *jitter* quando o provedor falha de forma transitória. Mensagens de outro tipo ou de outra partição
  (`hash mod count`) são ignoradas.
- A **reavaliação periódica** (padrão 300 s, com *jitter*) enfileira todas as Organizations `active` da partição, para detectar
  *drift* feito fora do loop.
- `workers` ciclos rodam em paralelo; uma mesma Organization nunca é reconciliada por dois ao mesmo tempo.

### 4.2 O ciclo atômico `reconcile(resourceId)`

Tudo numa só transação, com a linha de `ipm.organization` bloqueada (`FOR UPDATE`); Organization inexistente ou com
`reconciliation` `suspended` encerra o ciclo sem agir.

1. **Observa** o Zitadel, só leitura, pelos drivers (conta `ipm-organization-controller`, `IAM_ORG_MANAGER` de instância):
   - **organização** (API v2, `zitadel.org.v2.OrganizationService/ListOrganizations`, consulta pelo ID exato): `name` e estado;
   - **metadado** `deletionProtection` da organização (decisão 0074);
   - **preparo para os usuários** (`userAccess`, decisão 0081): o Project Grant de `roles-ipm` e os papéis das contas `ipm/user` e
     `ipm/serviceaccount` nela.

   O resultado é `present`, com `name`, `platformAccess` (`granted` com a organização ativa, `revoked` com ela desativada),
   `organizationState` (`active` ou `inactive`), `deletionProtection` e `userAccess`; `absent` **só** quando a consulta pelo ID teve
   sucesso e não trouxe resultado; e `unknown` para qualquer falha de leitura e para um estado que o contrato não conhece. Erro de
   leitura nunca vira `absent`.

   ```json
   {"presence": "present", "observedAt": "2026-10-16T10:52:24Z",
    "data": {"name": "acme", "platformAccess": "granted", "organizationState": "active", "deletionProtection": true}}
   ```

2. **Decide** com a função pura `decide(desired, observed)`, que compara `lifecycle`, `name`, `platformAccess`,
   `deletionProtection` e `userAccess`:
   - `unknown` nunca autoriza ação;
   - `lifecycle present` com a organização `absent` → `create` (`Missing`);
   - `name`, `platformAccess`, `deletionProtection` ou `userAccess` diferentes → `update` (`Drift`);
   - `lifecycle absent` com a organização `present` → `delete` (`DeletionRequested`);
   - senão, nada a fazer.

3. **Age**, se houver ação, de forma idempotente (o `resourceId` é o ID da organização no Zitadel). É a única identidade que escreve
   a Organization no Zitadel; não cria usuários nem autoriza o dono:
   - **`create`:** cria a organização com o `resourceId` como ID e o `name`. Um `409` (ID ou nome já usados) leva a ler a organização
     pelo ID: se existe com o nome esperado, é sucesso idempotente; senão, a ação falha com `Rejected` (um nome já usado por outra
     organização do Zitadel que a plataforma não reservou). Depois deixa a organização ativa ou desativada conforme
     `platformAccess`, e aplica o metadado e o preparo para os usuários.
   - **`update`:** renomeia quando o nome difere, ativa (`granted`) ou desativa (`revoked`) quando o estado difere, grava o metadado
     `deletionProtection` e completa o preparo para os usuários, só com o que falta. Só chama o Zitadel quando há diferença; o
     "já feito" também é sucesso.
   - **`delete`:** remove a organização; ausente também é sucesso (o Zitadel responde `200` a uma remoção repetida).

   O preparo para os usuários só é aplicado com `platformAccess = granted`.

4. **Reobserva** logo após a ação. Essa observação, feita depois da geração vigente, é a que confirma a convergência.

5. **Grava** no SSOT, na mesma transação: o `observed`, a presença, a fase, as conditions, a geração confirmada
   (`observed_generation`), a conclusão das Operations e, quando algo mudou, o `updated` no outbox (que o Publisher entrega). O
   `updated` só é gerado se a fase, as conditions, a reconciliação, o contador de falhas, a presença, o `observed` ou a geração
   confirmada mudaram.

### 4.3 Convergência, falhas e remoção

Como em toda feature (decisão 0072; fase e conditions em `docs/data/SSOT.md` §9 e §10), agora decididas pelo Controller:

- **`Ready`** quando `name`, `platformAccess`, `deletionProtection` e `userAccess` convergem **e** a observação foi feita depois da
  geração atual; a geração confirmada vai para `observed_generation` e a Operation vira `completed`. A ação concluída sozinha não é
  `Ready`: só a reobservação compatível converge. Com `lifecycle absent`, a fase é `Deleting`.
- **Remoção convergida** (`lifecycle absent` e organização `absent`): a Operation vira `completed`, a linha é apagada e o `updated`
  sai com `removed`.
- **Falha da ação:** conta no `failure_count` e marca a fase `Failed`; ao chegar no limite (`loop.failure_limit`, padrão 5) a
  `reconciliation` vira `suspended`, a Operation vira `failed` e o Controller grava um `desired` suspenso no outbox, para o estado
  ficar visível a quem acompanha. Falha transitória do provedor (indisponível, `429`, `5xx`) devolve a Organization à fila com
  *backoff*; erro permanente é registrado e a Organization só volta pela reavaliação periódica.
- **Prazos:** a geração que não converge dentro de `loop.progress_deadline_seconds` (padrão 300) recebe a condition
  `Progressing` `False` (`ProgressDeadlineExceeded`) e a Operation vira `failed`; uma Organization `unknown` por mais que o prazo
  recebe a condition `ObservationStale` (decisão 0090). Os dois saem sozinhos ao convergir.
- **Idempotência:** não há registro por ação (`organization_action_result` deixou de existir). Repetir o ciclo é seguro porque a
  decisão é recalculada do estado real a cada vez e as ações do provedor são idempotentes.
- **Reinício:** o Controller não guarda estado próprio. Ao subir, o Informer relê o `DESIRED` e a reavaliação periódica cobre as
  demais; um ciclo interrompido no meio desfaz a transação do banco e é refeito.

## 8. Estados

- **Fase** (`phase`): `Pending` ao gravar, `Reconciling`, `Ready`, `Failed` (não terminal) e `Deleting`. Diagrama:
  [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg). A ação concluída não é `Ready`: só a observação compatível converge.
- **Operation:** `accepted`, `in_progress`, `completed`, `failed` (limite de falhas ou prazo, decisão 0096) e `rejected` (com
  motivo, sem geração). Diagrama: [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ipm.organization` | Manager (intenção); Controller (observado, fase, conditions; remove a linha ao convergir a remoção) | Receiver (view `ipm.organization_v1`); Controller |
| `ipm.organization_operation` | Manager (insere); Controller (conclui) | Receiver (view `ipm.organization_operation_v1`) |
| `ipm.organization_outbox` | Manager (insere o `desired`); Controller (insere o `updated` e o `desired` suspenso) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Controller (e, no catálogo de permission, o Manager) |
| `UPDATED` | Publisher | consumidores do estado da Organization |
| Zitadel (a organização, o metadado e o preparo para os usuários) | Controller | Controller |

## 10. Verificação (2026-10-16, dev)

Histórico, anterior à decisão 0096 (então com seis componentes; o Controller substituiu três deles, e o comportamento observável é o
mesmo). Com os componentes no Compose e o Zitadel real, a suíte e2e (`tests/e2e`) cria a organização até `Ready`, renomeia,
desativa e reativa (`platformAccess`), remove (a observação confirma `absent` e a linha é apagada), e confere que nome reservado e
nome repetido nunca chegam ao Zitadel. Os testes de resiliência (`E2E_CHAOS=1`) derrubavam o Manager, o Publisher e os três
componentes do loop durante um pedido: em todos os casos o loop convergiu. Cada Organization de teste é removida pelo próprio loop
ao final, sem deixar organização no Zitadel.
