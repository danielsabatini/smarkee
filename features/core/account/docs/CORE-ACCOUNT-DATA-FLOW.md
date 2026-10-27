# core.account: fluxo de dados (do `sk account create` até `Ready`)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de `features/ipm/user/docs/IPM-USER-DATA-FLOW.md`. Segue **os dados** de um auto-cadastro de `core.account`: qual rota é chamada, qual é o payload de cada mensagem, o que cada componente grava no banco e com qual privilégio. A API síncrona é a [decisão 0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md); o loop unificado no Controller é a [0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md); a exclusão sem chamadas HTTP entre features é a [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md).

**Origem dos exemplos.** Os exemplos foram montados a partir do código e dos schemas, **não** de uma execução da stack nova (a suíte `tests/e2e` foi reescrita e ainda não foi executada contra os contêineres novos). Os valores (UUIDs, e-mail, horários) são fictícios. Fontes de verdade: contratos em [`schemas/`](../../../../schemas), tabelas em [`migrations/`](../migrations), semântica em [`docs/messaging/MESSAGING.md`](../../../../docs/messaging/MESSAGING.md), [`docs/messaging/NATS.md`](../../../../docs/messaging/NATS.md), [`docs/data/SSOT.md`](../../../../docs/data/SSOT.md) e [`docs/data/POSTGRESQL.md`](../../../../docs/data/POSTGRESQL.md). Este arquivo não as substitui: mostra um caso concreto.

**Comando.** `sk account create|get|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/core/accounts` (via gateway, anônimo) | `{givenName, familyName, email}` | nada |
| 2 | API → banco | SQL, uma transação | `202 {resourceId}` | `core.account`, `core.account_outbox` (o `desired`) |
| 3 | Publisher → Controller | NATS, Stream `DESIRED` | `desired` | `core.account_outbox.published_at` |
| 4 | Controller → Zitadel; Controller → banco | HTTP no Zitadel; SQL, uma transação | (nada publicado) | o usuário e as autorizações no Zitadel; `core.account` (observado, fase, conditions), `core.account_outbox` |
| 5 | Publisher → consumidores | NATS, Stream `UPDATED` | `updated` (a cada mudança de fase) | `core.account_outbox.published_at` |

Só a **API** admite pedidos e escreve o `desired` no SSOT de `core.account`; só o **Controller** escreve o estado observado, a fase e as conditions (e remove a linha quando a remoção converge). O Publisher não grava nas tabelas de recurso (só marca `published_at` no outbox). O tipo não tem Operation nem o Stream `REQUESTED` (decisão 0098); `OBSERVED`, `ACTION` e `RESULT` também não existem para ele (decisão 0096).

Diagramas em `flow/`, `architecture/`, `state/` e `database/` ainda mostram o modelo anterior (Receiver, Manager, Reconciler, Observer, Executor e Operation): **pendência declarada**. O texto deste documento é o vigente.

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API (no auto-cadastro) | UUIDv7 minúsculo | Identidade da conta. Vira o `userId` no Zitadel, e portanto o `sub` do token. |
| `messageId` | Quem emite a mensagem | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 | Mesmo valor em toda a cadeia, para rastrear o pedido do início ao fim. |
| `causationId` | Quem emite | `messageId` da mensagem que causou esta | Encadeia causa e efeito. |
| `resourceVersion` | API | inteiro, como texto | Concorrência otimista: o `PATCH` e o `DELETE` devolvem `409` se a versão diferir. |
| `Idempotency-Key` | Cliente (opcional) | texto | Só nas escritas autenticadas (`PATCH`, `DELETE`); o auto-cadastro não aceita. |

## 1. CLI → API: `POST /v1/core/accounts`

```bash
sk account create --name Ana --surname Souza --email ana.souza@example.com
```

O comando valida os dados, remove espaços das pontas e envia `POST <api-url>/v1/core/accounts` com `Content-Type: application/json`, **sem token** e sem `Idempotency-Key`. Em caso de sucesso mostra o `resourceId` e orienta confirmar o e-mail, definir a senha e rodar `sk auth login`.

| Item | Valor |
|---|---|
| Rota | `POST https://api-dev.smarkee.com.br/v1/core/accounts` (o gateway encaminha ao `core-account-api`; veja `infrastructure/dev/gateway/bootstrap/adc.yaml`) |
| Autenticação | **Nenhuma.** É a única escrita anônima; `requestedBy` vira `anonymous`. |
| Limite de taxa | Dois níveis: no gateway (10/min por IP) e na API (5/60 s por origem). Estourou: `429` com `Retry-After`. |
| Contrato do corpo | [`api-create-request`](../../../../schemas/core/account/api-create-request.v1.schema.json) (`additionalProperties: false`; uma senha enviada é `400`, sem repetir o valor) |

```json
{"givenName": "Ana", "familyName": "Souza", "email": "ana.souza@example.com"}
```

Resposta, **uniforme** (exista ou não o e-mail; [`api-registration-response`](../../../../schemas/core/account/api-registration-response.v1.schema.json)):

```http
HTTP/1.1 202 Accepted

{"resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"}
```

Erros (`schemas/common/api-error`): `400` (com `field`), `429` e `503 StorageUnavailable` (ambos com `Retry-After`). Não há senha: a pessoa a define pela página do Zitadel, no link enviado por e-mail.

## 2. API → banco: a admissão

Numa **única transação** (`api/store/admission.py`):

1. `pg_advisory_xact_lock(hashtext('core.account.email:<e-mail>'))`, com o e-mail normalizado (`strip().lower()`), serializa cadastros concorrentes do mesmo e-mail.
2. Consulta se já existe conta `lifecycle = 'present'` com esse e-mail.
3. Se não existe: `INSERT` em `core.account` (geração 1, versão 1, fase `Pending`) e `INSERT` do `desired` em `core.account_outbox`.
4. Se existe (`NameInUse`): a transação é **revertida**, nada é gravado nem publicado, e a API responde o mesmo `202` com um `resourceId` novo (que não corresponde a nenhum registro). Isso não revela cadastros (`RESOURCE-CONTROL-LOOP.md` §6.1.2).

O `desired` da criação: `lifecycle = present`, `reconciliation = active`, `platformAccess = granted`, `platformPermissions` (`CORE_ACCOUNT_API_PLATFORM_PERMISSIONS`), `deletionProtection = true` e os dados pessoais.

### Rotas autenticadas

| Rota | Quem | Regra |
|---|---|---|
| `GET /v1/core/accounts/{id}` | O dono (`sub == resourceId`) ou `core.account.admin`, permissão `core.account.get` | `200` com o `Resource`; outro solicitante recebe `404` |
| `PATCH /v1/core/accounts/{id}` | Idem, permissão `core.account.delete` | Só altera `deletionProtection`. Bloqueia a linha (`FOR UPDATE`), confere `resourceVersion` (`409`), conta em remoção (`409 NotPresent`); sem mudança efetiva devolve `200` sem gravar. Com mudança: geração + 1, versão + 1, fase `Reconciling`, novo `desired` no outbox, `200` + `Resource` |
| `DELETE /v1/core/accounts/{id}?resourceVersion=` | Idem, permissão `core.account.delete` | Ver seção 6. `202` + `Resource` (`phase = Deleting`) |

Escritas autenticadas aceitam `Idempotency-Key` (`core.account_idempotency`): mesma chave e mesmo conteúdo devolvem o recurso atual; conteúdo diferente é `422 IdempotencyKeyReused`. Não há listagem.

O `Resource` devolvido tem `resourceId`, `resourceVersion`, `desiredGeneration`, `observedGeneration`, `phase`, `conditions`, `desired`, `observed`, `createdAt` e `updatedAt` ([exemplo](../../../../schemas/core/account/resource.example.json)). A convergência se lê no próprio recurso: `observedGeneration >= desiredGeneration` com `phase` `Ready` ou `Failed`; depois do `DELETE`, `404`.

## 3. Outbox → NATS

O Publisher (`core-account-publisher`) lê o outbox em ordem e publica em `manager.desired.core.account.<resourceId>.changed`, com `Nats-Msg-Id` igual ao `messageId`, e marca `published_at` depois da confirmação. O `desired` publicado (a API é o `emitter`):

```json
{
  "messageType": "desired", "emitter": "api", "module": "core", "resourceType": "account",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operation": "changed", "desiredGeneration": 1,
  "requestedBy": "anonymous", "publishedBy": "core-account-publisher",
  "data": {"lifecycle": "present", "reconciliation": "active", "platformAccess": "granted",
           "platformPermissions": ["core.account.delete", "core.account.get"], "deletionProtection": true,
           "givenName": "Ana", "familyName": "Souza", "email": "ana.souza@example.com"}
}
```

O `desired` de criação carrega dados pessoais (o Controller precisa deles): ficam no SSOT, no outbox e no Stream `DESIRED`, e nunca em logs, erros ou métricas. **Pendência de privacidade:** o outbox não tem retenção implementada (`docs/platform/IMPLEMENTATION-STATUS.md`).

## 4. Controller (`core-account-controller`)

Decisão 0096, no padrão do Kubernetes Controller (Informer + Workqueue, AGENTS.md §2.7). A lógica está em `src/core_account/controller/` ([README](../src/core_account/controller/README.md)).

### 4.1 Entrada: Informer, fila e reavaliação

- O **Informer** consome `manager.desired.core.account.>` (consumer `core-account-controller-desired-<instância>`). A mensagem só avisa que o recurso mudou: o `resourceId` entra na **Workqueue**, e quem decide lê o `desired` no SSOT.
- A **Workqueue** deduplica por `resourceId` e repete com *backoff* exponencial com *jitter* quando o provedor falha de forma transitória. Mensagens de outra partição (`hash mod count`) são ignoradas.
- A **reavaliação periódica** (padrão 300 s, com *jitter*) enfileira as contas `active` da partição, para detectar *drift* feito fora do loop.

### 4.2 O ciclo atômico `reconcile(resourceId)`

Numa só transação, com a linha bloqueada (`FOR UPDATE`); conta inexistente ou com `reconciliation = suspended` encerra o ciclo sem agir.

1. **Observa** o Zitadel (só leitura): o usuário (`accountState`, `initial` até a senha ser definida, e `emailVerified`), as permissões nos projetos da plataforma e o metadado `deletionProtection`. O resultado é `present`, `absent` **só** com o `404` do usuário exato, ou `unknown` para qualquer falha de leitura (que nunca autoriza ação). O `observed` não traz dados pessoais:

   ```json
   {"presence": "present", "observedAt": "2026-10-27T12:00:04Z",
    "data": {"emailVerified": false, "accountState": "initial", "platformAccess": "granted",
             "platformPermissions": ["core.account.delete", "core.account.get"], "deletionProtection": true}}
   ```

2. **Decide** com a função pura `decide(desired, observed)` (`domain/decision.py`), sobre `lifecycle`, `platformAccess`, `platformPermissions` (as desejadas precisam estar contidas nas observadas) e `deletionProtection`: `create`, `update` (*drift*), `delete` ou nada. Os dados pessoais são imutáveis.
3. **Age**, de forma idempotente (o `resourceId` é o ID do usuário no Zitadel):
   - **`create`:** cria o usuário humano **sem senha** na organização `register` (o Zitadel envia o e-mail de verificação, cuja página também define a senha) e concede as permissões do `desired`, cada uma no projeto do seu módulo (decisão 0032), mais o metadado `deletionProtection`;
   - **`update`:** ajusta autorizações e metadado;
   - **`delete`:** remove o usuário; ausente também é sucesso.
4. **Reobserva** logo após a ação. Só essa observação, feita depois da geração vigente, confirma a convergência.
5. **Grava** no SSOT, na mesma transação: o `observed`, a presença, a fase, as conditions, a geração confirmada (`observed_generation`) e, quando algo mudou, o `updated` no outbox.

### 4.3 Convergência, falhas e remoção

- **`Ready`** quando o observado converge **e** a observação é posterior à geração atual. A ação concluída sozinha não é `Ready`.
- **Falha da ação:** conta no `failure_count` e marca `Failed`; ao chegar no limite (`loop.failure_limit`, padrão 5) a `reconciliation` vira `suspended` e o Controller grava um `desired` suspenso no outbox. Falha transitória devolve a conta à fila com *backoff*.
- **Prazos:** geração que não converge em `loop.progress_deadline_seconds` recebe `Progressing=False` (`ProgressDeadlineExceeded`); conta `unknown` por mais que o prazo recebe `ObservationStale` (decisão 0090). Saem sozinhos ao convergir.
- **Remoção convergida** (`lifecycle absent` e usuário `absent`): o Controller **apaga a linha** de `core.account` e grava o `updated` com `removed`.
- **Idempotência e reinício:** não há registro por ação. A decisão é recalculada do estado real a cada ciclo; um ciclo interrompido desfaz a transação e é refeito.

## 5. Ativação e login

O usuário recebe o e-mail do Zitadel ("Verificar e-mail"), define a senha pela página dele e passa a autenticar com `sk auth login`. O `accountState` observado muda de `initial` para `active` no próximo ciclo. Detalhes e limitações no [README da feature](../README.md), seção "Como ativar a conta".

## 6. Remoção: `DELETE /v1/core/accounts/{id}?resourceVersion=`

Exige a permissão `core.account.delete` (o dono ou `core.account.admin`) e a `resourceVersion` da última leitura. A conta nasce com `deletionProtection = true`; o `PATCH` a desliga (200), e só então o `DELETE` segue (`409 DeletionProtected` enquanto ligada).

**Exclusão segura (decisões 0040 e 0100).** Antes de aceitar, a API confere se a conta ainda tem recursos, **sem chamar outras APIs**: lê as projeções locais do Stream `DESIRED` (`ipm.organization`, `bsm.account` e `sum.service`, por `ownerAccountId` e `lifecycle = present`):

| Condição | Resposta |
|---|---|
| `sub` do token diferente do `resourceId` (só o dono consegue verificar) | `409 ResourcesNotVerifiable` |
| projeção ainda sincronizando | `503 ProjectionSyncPending` (`Retry-After: 2`) |
| há Organizations, serviços ou contas de cobrança | `409 ResourcesAttached` |
| proteção ligada | `409 DeletionProtected` |

`DELETE` de conta já em remoção (`lifecycle absent`) pula essas checagens (idempotente).

Aceita a remoção, a API, na transação: `UPDATE` com `lifecycle = 'absent'`, geração + 1, versão + 1, fase `Deleting` (**não apaga a linha**) e grava no outbox um `desired` **sem dados pessoais** (`lifecycle absent`, `platformAccess` e `platformPermissions`). Responde `202` + `Resource`. O Controller remove o usuário no Zitadel e, ao convergir, apaga a linha (seção 4.3). O outbox e a idempotência permanecem até a limpeza por retenção (papel `core_maintenance`).

## 7. Estados

Fase do recurso: [`state/01-fase-do-recurso`](state/01-fase-do-recurso.svg) (modelo anterior, vale quanto às fases). A Operation deixou de existir (decisão 0098); [`state/02-operation`](state/02-operation.svg) é histórico.

## 8. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `core.account` | API (intenção); Controller (observado, fase, conditions; remove a linha ao convergir a remoção) | API (view `core.account_v1`); Controller |
| `core.account_idempotency` | API | API |
| `core.account_outbox` | API (o `desired`); Controller (o `updated` e o `desired` suspenso); Publisher (`published_at`) | Publisher |
| `DESIRED` | Publisher | Controller; API (projeções das outras features, para a exclusão segura) |
| `UPDATED` | Publisher | consumidores do estado da conta |
| Zitadel (usuário, autorizações e metadado) | Controller | Controller |

| Papel de banco | Privilégio |
|---|---|
| `core_account_api` | `SELECT`, `INSERT` e `UPDATE` em `core.account`; `SELECT` em `core.account_v1`; `INSERT` em `core.account_outbox`; `SELECT` e `INSERT` em `core.account_idempotency`; **sem `DELETE`** |
| `core_account_controller` | `SELECT`, `UPDATE` e `DELETE` em `core.account`; só `INSERT` em `core.account_outbox` |
| `core_account_publisher` | `SELECT` em `core.account_outbox` e `UPDATE (published_at)` |
| `core_maintenance` | `SELECT` e `DELETE` em `core.account_outbox` e `core.account_idempotency` |

Origem: [`migrations/0011-account-api.sql`](../migrations/0011-account-api.sql) e `infrastructure/dev/database/bootstrap/core.sql`.

Consultas úteis (dev, somente leitura):

```sql
SELECT resource_id, phase, resource_version, presence, failure_count FROM core.account;
SELECT sequence, subject, published_at FROM core.account_outbox ORDER BY sequence;
```
