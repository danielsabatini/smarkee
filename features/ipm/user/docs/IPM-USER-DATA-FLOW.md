# ipm.user: fluxo de dados (do `POST` até o usuário na organização do Zitadel)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/ipm/organization/docs/IPM-ORGANIZATION-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose),
verificados pela suíte e2e (`tests/e2e`) contra o Zitadel real. A decisão de desenho é a
[0077](../../../../.decisions/0077-ipm-user-usuarios-da-organizacao.md); o loop unificado no Controller é a
[0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md), que substituiu o Observer, o Reconciler e o
Executor deste tipo.

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, e-mails)
são fictícios.

**Comando.** `sk ipm user create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

O usuário da Organization (`ipm.user`) é um usuário humano do Zitadel criado **dentro** da organização do cliente, com permissões
da plataforma dadas por autorização no Project Grant de `roles-ipm` para essa organização. Quem cria é o dono da Organization
(o root, a Account que a criou) ou um usuário dela com `ipm.user.create`. Criar um usuário
(`POST /v1/ipm/users`) não cria nada no Zitadel diretamente: o pedido percorre o loop, como em toda feature.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/ipm/users` (via gateway) | `{organizationId, givenName, familyName, email, permissions}` | nada |
| 1a | Receiver → Receiver da Organization | HTTP, na rede interna, com o token de quem pede | `GET /v1/ipm/organizations/{id}` (só para o root) | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `ipm.user`, `ipm.user_operation`, `ipm.user_outbox` |
| 4 | Publisher → Controller | NATS, Stream `DESIRED` | `desired` | `ipm.user_outbox.published_at` |
| 5 | Controller → Zitadel; Controller → banco | HTTP no Zitadel; SQL, uma transação | (nada publicado) | o usuário, a autorização e o metadado no Zitadel; `ipm.user` (observado, fase, conditions), `ipm.user_operation` → `completed`, `ipm.user_outbox` |
| 6 | Publisher → consumidores | NATS, Stream `UPDATED` | `updated` (a cada mudança de fase) | `ipm.user_outbox.published_at` |

Só o **Manager** admite pedidos e escreve o `desired` no SSOT de `ipm.user`; só o **Controller** escreve o estado observado, a fase, as
conditions e a conclusão das Operations (e remove a linha quando a remoção converge). Receiver e Publisher não gravam nas tabelas de
recurso (o Publisher só marca `published_at` no outbox). O tipo só usa os Streams `REQUESTED` e `DESIRED` (mais `UPDATED`, de saída):
`OBSERVED`, `ACTION` e `RESULT` não existem para ele (decisão 0096).

Diagramas: criar [`flow/01-criar-usuario.svg`](flow/01-criar-usuario.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), alterar as permissões e remover [`03`](flow/03-alterar-roles-e-remover.svg), falhas no
Manager e na mensageria [`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação
[`05`](flow/05-falhas-na-reconciliacao.svg) e na ação do provedor [`06`](flow/06-falhas-no-executor.svg). Componentes:
[`architecture/01-componentes.svg`](architecture/01-componentes.svg). Estados:
[`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg). Banco:
[`database/01-er-fisico.svg`](database/01-er-fisico.svg).

> **Diagramas pendentes (decisão 0096):** os SVGs e os `.mmd` de `flow/`, `architecture/` e `state/` ainda mostram o modelo anterior,
> com Observer, Reconciler e Executor, os Streams `OBSERVED`, `ACTION` e `RESULT` e `user_action_result`. O texto deste documento é
> o vigente.

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver | UUIDv7 minúsculo | Identidade do usuário. Vira o ID do usuário no Zitadel (e o `sub` do token dele), então repetir a criação não duplica. |
| `organizationId` | Cliente | `resourceId` da Organization | A organização do Zitadel onde o usuário vive. Imutável. |
| `operationId`, `requestDigest` | Receiver | UUIDv7 (ou determinístico com `Idempotency-Key`); SHA-256 do pedido | Identidade da Operation; a repetição produz o mesmo valor. |
| `messageId` | Quem emite | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId`, `causationId` | Receiver; quem emite | UUIDv7; `messageId` da causa | Rastreiam o pedido do início ao fim e encadeiam causa e efeito. |

## 1. CLI → Receiver: `POST /v1/ipm/users`

O corpo é `{"organizationId", "givenName", "familyName", "email", "permissions"}` (`schemas/ipm/user/api-create-request`; sem
senha). O Receiver valida o token (audience `roles-ipm`) e exige a permissão `ipm.user.create`. Depois decide **se quem pede age na
Organization** (decisão 0077):

- **operador** (`ipm.user.admin`): qualquer Organization, sem cota;
- **usuário da Organization**: o próprio registro no SSOT do tipo (`resourceId` igual ao `sub` do token, `lifecycle present`)
  aponta para essa Organization;
- **root**: o Receiver da Organization responde `200` ao `GET /v1/ipm/organizations/{organizationId}` feito com o token de quem
  pede (decisão 0040); `404` ou `403` dele é "não age", e falha dele é `503 OrganizationUnavailable`, repetível.

Em seguida confere as permissões: todas no catálogo `grantablePermission` do contrato (o mesmo que a `ipm/organization` grava no Project
Grant de cada Organization, decisão 0081) e, sem `ipm.user.bind`, só permissões que o próprio solicitante tem (o root e o operador têm o `bind`). Por fim a
cota de usuários da Organization (`IPM_USER_RECEIVER_API_USER_QUOTA`, padrão 5). O e-mail é normalizado (minúsculas), porque
também é o nome de login. Publica `requested` em `receiver.requested.ipm.user.<resourceId>.create`:

```json
{
  "messageId": "01a15e61-6d1e-7096-878a-d5f450b85801", "schemaVersion": "1.0", "messageType": "requested",
  "emitter": "receiver", "module": "ipm", "resourceType": "user",
  "resourceId": "01a15e61-6d1e-7096-878a-d5f450b858f2", "operation": "create",
  "requestedBy": "0199c8a4-0000-7000-8000-00000000beef", "correlationId": "01a15e61-6d1e-7096-878a-d5f450b85802",
  "data": {
    "operationId": "01a15e61-6d1e-7096-878a-d5f450b85803", "requestDigest": "5f2b8c0e…4c8b",
    "specification": {"organizationId": "01a15e61-1eca-71b3-96b9-4068290bd618", "givenName": "Bia",
                      "familyName": "Lima", "email": "bia.lima@example.com",
                      "permissions": ["ipm.user.get", "ipm.user.list"], "deletionProtection": false},
    "organizationQuotaLimit": 5
  }
}
```

As demais rotas: `GET /{resourceId}` (todo usuário lê o próprio registro sem permissão, como o `SelfSubjectReview` do Kubernetes; os
demais exigem `ipm.user.get` e o escopo), `GET ?organizationId=` (lista de uma Organization), `PATCH` (permissões, com o mesmo
catálogo e a mesma regra do `bind` sobre o que entra **e** o que sai; `deletionProtection`; `reconciliation` só do operador),
`DELETE?resourceVersion=` e `GET .../operations/{operationId}`. Um usuário de outra Organization responde `404`, para não
revelar que existe. Erros no formato `api-error`: `400` entrada inválida (sem repetir o valor enviado), `401`, `403`, `404`,
`409` versão desatualizada ou usuário protegido, `422` reuso da `Idempotency-Key`, `503` com `Retry-After`. Diagrama:
[`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg). O contrato descritivo é `openapi.json`.

## 2. Manager consome `requested` e grava

O consumer durável `ipm-user-manager-requested` (pull, ACK explícito) entrega a mensagem ao handler, que valida o envelope e os
dados (desvio é `TERM`), aplica tudo numa transação com a linha bloqueada e as travas consultivas, e faz o ACK depois do
`COMMIT` (falha transitória do banco é `RETRY`).

### 2.1 Decisão (domínio puro, `domain/user.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar | e-mail já usado por outro usuário presente da mesma Organization (trava `ipm.user.email:<organização>:<e-mail>`) | recusa `validation` |
| criar ou alterar | permissão fora do módulo `ipm` (o Controller só concede em `roles-ipm`) | recusa `validation` |
| criar | cota de usuários da Organization esgotada (conferida de novo sob trava por Organization; o Receiver só pré-checa) | recusa `validation` |
| alterar ou remover | usuário inexistente ou já removido | recusa `not_found` |
| alterar ou remover | `resourceVersion` diferente da atual | recusa `conflict` |
| remover | `deletionProtection` igual a `true` (o usuário nasce desprotegido; registro sem o campo vale desprotegido) | recusa `protected`; antes dela, o Receiver já responde `409 DeletionProtected` |
| qualquer | senão | aceita: `desired` com a nova geração; ao remover, `lifecycle absent` **sem** `givenName`, `familyName` e `email` |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `ipm.user` (geração 1, versão 1, fase `Pending`), com o `desired` = `lifecycle present` mais a
  especificação. Quem pediu não entra no `desired` (fica na Operation).
- **Alterar aceito:** geração + 1, versão + 1, fase `Reconciling`. **Remover aceito:** `lifecycle absent`, fase `Deleting`.
- **Operation** e **outbox** como em toda feature. Reentrega com o mesmo `operationId` não grava nada.

## 3. Outbox → NATS

O Publisher (`ipm-user-publisher`) publica em `manager.desired.ipm.user.<resourceId>.changed`, com `Nats-Msg-Id` igual ao
`messageId`, e marca `published_at` depois da confirmação. O `desired` publicado:

```json
{
  "messageType": "desired", "emitter": "manager", "module": "ipm", "resourceType": "user",
  "resourceId": "01a15e61-6d1e-7096-878a-d5f450b858f2", "operation": "changed", "desiredGeneration": 1,
  "publishedBy": "ipm-user-publisher",
  "data": {"lifecycle": "present", "reconciliation": "active",
           "organizationId": "01a15e61-1eca-71b3-96b9-4068290bd618", "permissions": ["ipm.user.get", "ipm.user.list"],
           "deletionProtection": false, "givenName": "Bia", "familyName": "Lima", "email": "bia.lima@example.com"}
}
```

O `desired` carrega dados pessoais enquanto o usuário existe (o Controller precisa deles para criar): ficam no SSOT e no Stream
`DESIRED`, e nunca em logs, erros ou métricas (`SCHEMA.md`, Classificação).

## 4. Controller (`ipm-user-controller`)

Decisão 0096, no padrão do Kubernetes Controller (Informer + Workqueue, AGENTS.md §2.7). Um único processo observa o Zitadel,
decide, age e reobserva; a lógica está em `src/ipm_user/controller/` (README do papel:
[`controller`](../src/ipm_user/controller/README.md)).

### 4.1 Entrada: Informer, fila e reavaliação

- O **Informer** consome o Stream `DESIRED` (`manager.desired.ipm.user.>`, consumer `ipm-user-controller-desired-<instância>`) com
  barreira de sincronização inicial. A mensagem só avisa que o recurso mudou: o `resourceId` entra na **Workqueue**, e quem decide
  lê o `desired` no SSOT.
- A **Workqueue** deduplica por `resourceId` (várias mensagens do mesmo usuário viram um só ciclo) e repete com *backoff* exponencial
  com *jitter* quando o provedor falha de forma transitória. Mensagens de outro tipo ou de outra partição (`resourceId`
  determinístico, `hash mod count`) são ignoradas.
- A **reavaliação periódica** (padrão 300 s, com *jitter*) enfileira todos os usuários `active` da partição, para detectar *drift*
  feito fora do loop.
- `workers` ciclos rodam em paralelo; um mesmo usuário nunca é reconciliado por dois ao mesmo tempo.

### 4.2 O ciclo atômico `reconcile(resourceId)`

Tudo numa só transação, com a linha de `ipm.user` bloqueada (`FOR UPDATE`); usuário inexistente ou com `reconciliation` `suspended`
encerra o ciclo sem agir.

1. **Observa** o Zitadel, só leitura (conta `ipm-user-controller`, `ORG_OWNER_VIEWER` na organização de cliente), pelos drivers:
   - **usuário** (`GET /v2/users/{resourceId}`): `userState` (`initial` enquanto a senha não foi definida) e `emailVerified`;
   - **autorização** (`ListAuthorizations` do usuário): as `permissions` dele em `roles-ipm` (as de outros projetos não contam);
   - **metadado** `deletionProtection` do usuário (decisão 0074).

   O resultado é `present` com esses campos, `absent` **só** com o `404` do usuário exato, e `unknown` para qualquer falha de
   leitura. O `observed` não traz dados pessoais.

   ```json
   {"presence": "present", "observedAt": "2026-10-21T12:12:39Z",
    "data": {"emailVerified": false, "userState": "initial", "permissions": ["ipm.user.get", "ipm.user.list"],
             "deletionProtection": false}}
   ```

2. **Decide** com a função pura `decide(desired, observed)`, que compara `lifecycle`, `permissions` e `deletionProtection`:
   - `unknown` nunca autoriza ação;
   - `lifecycle present` com o usuário `absent` → `create`;
   - `permissions` ou `deletionProtection` diferentes → `update` (*drift*);
   - `lifecycle absent` com o usuário `present` → `delete`;
   - senão, nada a fazer.

   Os dados pessoais e a Organization não são campos gerenciados: são imutáveis e definidos na criação.

3. **Age**, se houver ação, de forma idempotente (o `resourceId` é o ID do usuário no Zitadel), com `ORG_USER_CREATOR` na organização
   e `PROJECT_GRANT_OWNER` no Project Grant de `roles-ipm` para ela (dados pelo loop da `ipm/organization` a cada organização,
   decisão 0081):
   - **`create`:** cria o usuário humano **sem senha** na organização do `desired` (`organizationId`), com o `resourceId` como ID e
     o e-mail como nome de login; o Zitadel envia o e-mail de verificação, cuja página também define a senha. Usuário já existente
     com o mesmo ID leva a lê-lo: mesmo e-mail e mesma organização é sucesso idempotente; senão, a ação falha com `Rejected`.
     Depois deixa as permissões e o metadado.
   - **`update`:** confere que o usuário existe e é da organização do `desired`; deixa a autorização em `roles-ipm` com
     **exatamente** as permissões do `desired` (cria, atualiza ou remove) e grava o metadado `deletionProtection`.
   - **`delete`:** remove o usuário; ausente também é sucesso.

   O Project Grant é o teto: uma permissão do `roles-ipm` fora do catálogo da organização é recusada pelo Zitadel (`Rejected`,
   verificado pelo e2e).

4. **Reobserva** logo após a ação. Essa observação, feita depois da geração vigente, é a que confirma a convergência.

5. **Grava** no SSOT, na mesma transação: o `observed`, a presença, a fase, as conditions, a geração confirmada
   (`observed_generation`), a conclusão das Operations e, quando algo mudou, o `updated` no outbox (que o Publisher entrega). O
   `updated` só é gerado se a fase, as conditions, a reconciliação, o contador de falhas, a presença, o `observed` ou a geração
   confirmada mudaram.

### 4.3 Convergência, falhas e remoção

Como em toda feature (decisão 0072; fase e conditions em `docs/data/SSOT.md` §9 e §10), agora decididas pelo Controller:

- **`Ready`** quando `permissions` e `deletionProtection` convergem **e** a observação foi feita depois da geração atual; a
  geração confirmada vai para `observed_generation` e a Operation vira `completed`. A ação concluída sozinha não é `Ready`: só a
  reobservação compatível converge.
- **Remoção convergida** (`lifecycle absent` e usuário `absent`): a Operation vira `completed`, a linha é apagada e o `updated` sai
  com `removed`.
- **Falha da ação:** conta no `failure_count` e marca a fase `Failed`; ao chegar no limite (`loop.failure_limit`, padrão 5) a
  `reconciliation` vira `suspended`, a Operation vira `failed` e o Controller grava um `desired` suspenso no outbox, para o estado
  ficar visível a quem acompanha. Falha transitória do provedor devolve o usuário à fila com *backoff*; erro permanente é
  registrado e o usuário só volta pela reavaliação periódica.
- **Prazos:** a geração que não converge dentro de `loop.progress_deadline_seconds` (padrão 300) recebe a condition
  `Progressing` `False` (`ProgressDeadlineExceeded`) e a Operation vira `failed`; um usuário `unknown` por mais que o prazo recebe a
  condition `ObservationStale` (decisão 0090). Os dois saem sozinhos ao convergir.
- **Idempotência:** não há registro por ação (`user_action_result` deixou de existir). Repetir o ciclo é seguro porque a decisão é
  recalculada do estado real a cada vez e as ações do provedor são idempotentes.
- **Reinício:** o Controller não guarda estado próprio. Ao subir, o Informer relê o `DESIRED` e a reavaliação periódica cobre os
  demais; um ciclo interrompido no meio desfaz a transação do banco e é refeito.

## 8. Estados

- **Fase** (`phase`): [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg). A ação concluída não é `Ready`.
- **Operation:** [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ipm.user` | Manager (intenção); Controller (observado, fase, conditions; remove a linha ao convergir a remoção) | Receiver (view `ipm.user_v1`); Controller |
| `ipm.user_operation` | Manager (insere); Controller (conclui) | Receiver (view `ipm.user_operation_v1`) |
| `ipm.user_outbox` | Manager (insere o `desired`); Controller (insere o `updated` e o `desired` suspenso) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Controller (e, nos catálogos de permission, role e group, o Manager) |
| `UPDATED` | Publisher | consumidores do estado do usuário |
| Zitadel (o usuário, a autorização em `roles-ipm` e o metadado) | Controller | Controller |

## 10. Verificação (2026-10-21, dev)

Histórico, anterior à decisão 0096 (então com seis componentes; o Controller substituiu três deles, e o comportamento observável é o mesmo). Com os componentes no Compose e o Zitadel real, numa Organization preparada pelo operador:

- a suíte e2e (`tests/e2e`) cria o usuário até `Ready` (geração confirmada), troca as permissões, liga a proteção e o remove pelo loop,
  e confirma que uma permissão fora do Grant é recusada pelo Zitadel;
- um usuário humano da Organization entrou pela aplicação `cli` (fluxo de login v2, com PKCE): o token trouxe a audience de
  `roles-ipm` e as permissões dele, ligadas à organização dele; pelo gateway, ele leu o próprio registro e listou os usuários e,
  com `ipm.organization.get`, leu a Organization (o Receiver da Organization o reconheceu pelo Receiver do User). Sem
  `ipm.user.create`, a criação foi recusada (`403`).
