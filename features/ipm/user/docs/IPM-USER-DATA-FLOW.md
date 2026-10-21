# ipm.user: fluxo de dados (do `POST` até o usuário na organização do Zitadel)

Documento de fluxo de dados da feature, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e de
`features/ipm/organization/docs/IPM-ORGANIZATION-DATA-FLOW.md`. Todos os passos estão implementados e rodam no dev (Compose),
verificados pela suíte e2e (`tests/e2e`) contra o Zitadel real. A decisão de desenho é a
[0077](../../../../.decisions/0077-ipm-user-usuarios-da-organizacao.md).

**Origem dos exemplos.** Os exemplos foram tirados de uma execução no dev e sanitizados: os valores (UUIDs, horários, e-mails)
são fictícios.

**Comando.** `sk ipm user create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

O usuário da Organization (`ipm.user`) é um usuário humano do Zitadel criado **dentro** da organização do cliente, com roles
da plataforma dadas por autorização no Project Grant de `roles-ipm` para essa organização. Quem cria é o dono da Organization
(o root, a Account que a criou) ou um usuário dela com `ipm.user.create`. Criar um usuário
(`POST /v1/ipm/users`) não cria nada no Zitadel diretamente: o pedido percorre o loop, como em toda feature.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/ipm/users` (via gateway) | `{organizationId, givenName, familyName, email, roles}` | nada |
| 1a | Receiver → Receiver da Organization | HTTP, na rede interna, com o token de quem pede | `GET /v1/ipm/organizations/{id}` (só para o root) | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `ipm.user`, `ipm.user_operation`, `ipm.user_outbox` |
| 4 | Publisher → consumidores | NATS, Stream `DESIRED` | `desired` | `ipm.user_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `ipm.user` (observação), `ipm.user_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → Zitadel; Executor → Manager | HTTP no Zitadel; NATS, Stream `RESULT` | `completed` | `ipm.user_action_result`, `ipm.user` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `ipm.user` → `Ready`, `ipm.user_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `ipm.user_outbox` |

Só o **Manager** escreve no SSOT de `ipm.user`. Receiver, Reconciler, Executor, Observer e Publisher não gravam nas tabelas de
recurso (o Publisher só marca `published_at` no outbox).

Diagramas: criar [`flow/01-criar-usuario.svg`](flow/01-criar-usuario.svg), erros antes do loop
[`02`](flow/02-validacao-e-borda.svg), alterar as roles e remover [`03`](flow/03-alterar-roles-e-remover.svg), falhas no
Manager e na mensageria [`04`](flow/04-falhas-no-manager-e-mensageria.svg), na reconciliação
[`05`](flow/05-falhas-na-reconciliacao.svg) e no Executor [`06`](flow/06-falhas-no-executor.svg). Componentes:
[`architecture/01-componentes.svg`](architecture/01-componentes.svg). Estados:
[`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg) e [`state/02-operation.svg`](state/02-operation.svg). Banco:
[`database/01-er-fisico.svg`](database/01-er-fisico.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | Receiver | UUIDv7 minúsculo | Identidade do usuário. Vira o ID do usuário no Zitadel (e o `sub` do token dele), então repetir a criação não duplica. |
| `organizationId` | Cliente | `resourceId` da Organization | A organização do Zitadel onde o usuário vive. Imutável. |
| `operationId`, `requestDigest` | Receiver | UUIDv7 (ou determinístico com `Idempotency-Key`); SHA-256 do pedido | Identidade da Operation; a repetição produz o mesmo valor. |
| `messageId` | Quem emite | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId`, `causationId` | Receiver; quem emite | UUIDv7; `messageId` da causa | Rastreiam o pedido do início ao fim e encadeiam causa e efeito. |
| `actionId` | Reconciler | `<resourceId>.<desiredGeneration>.<operação>.<messageId do observed>` | Identidade determinística da decisão; Executor e Manager a usam para ser idempotentes. |

## 1. CLI → Receiver: `POST /v1/ipm/users`

O corpo é `{"organizationId", "givenName", "familyName", "email", "roles"}` (`schemas/ipm/user/api-create-request`; sem
senha). O Receiver valida o token (audience `roles-ipm`) e exige a role `ipm.user.create`. Depois decide **se quem pede age na
Organization** (decisão 0077):

- **operador** (`ipm.user.admin`): qualquer Organization, sem cota;
- **usuário da Organization**: o próprio registro no SSOT do tipo (`resourceId` igual ao `sub` do token, `lifecycle present`)
  aponta para essa Organization;
- **root**: o Receiver da Organization responde `200` ao `GET /v1/ipm/organizations/{organizationId}` feito com o token de quem
  pede (decisão 0040); `404` ou `403` dele é "não age", e falha dele é `503 OrganizationUnavailable`, repetível.

Em seguida confere as roles: todas no catálogo `grantableRole` do contrato (o mesmo que a `ipm/organization` grava no Project
Grant de cada Organization, decisão 0081) e, sem `ipm.user.bind`, só roles que o próprio solicitante tem (o root e o operador têm o `bind`). Por fim a
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
                      "roles": ["ipm.user.get", "ipm.user.list"], "deletionProtection": false},
    "organizationQuotaLimit": 5
  }
}
```

As demais rotas: `GET /{resourceId}` (todo usuário lê o próprio registro sem role, como o `SelfSubjectReview` do Kubernetes; os
demais exigem `ipm.user.get` e o escopo), `GET ?organizationId=` (lista de uma Organization), `PATCH` (roles, com o mesmo
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
| criar ou alterar | role fora do módulo `ipm` (o Executor só concede em `roles-ipm`) | recusa `validation` |
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
           "organizationId": "01a15e61-1eca-71b3-96b9-4068290bd618", "roles": ["ipm.user.get", "ipm.user.list"],
           "deletionProtection": false, "givenName": "Bia", "familyName": "Lima", "email": "bia.lima@example.com"}
}
```

O `desired` carrega dados pessoais enquanto o usuário existe (o Executor precisa deles para criar): ficam no SSOT e no Stream
`DESIRED`, e nunca em logs, erros ou métricas (`SCHEMA.md`, Classificação).

## 4. Observer (`ipm-user-observer`)

Lê o Zitadel só de leitura, com a conta `ipm-user-observer` (`ORG_OWNER_VIEWER` em cada organização de cliente), pelos drivers
espelhados dos do Executor (decisão 0073):

- **usuário** (`GET /v2/users/{resourceId}`): `userState` (`initial` enquanto a senha não foi definida) e `emailVerified`;
- **autorização** (`ListAuthorizations` do usuário): as `roles` dele em `roles-ipm` (as de outros projetos não contam);
- **metadado** `deletionProtection` do usuário (decisão 0074).

Produz `present` com esses campos, `absent` **só** com o `404` do usuário exato, e `unknown` para qualquer falha de leitura.
O `observed` não traz dados pessoais.

```json
{"messageType": "observed", "emitter": "observer", "presence": "present", "observedAt": "2026-10-21T12:12:39Z",
 "observedGeneration": 1,
 "data": {"emailVerified": false, "userState": "initial", "roles": ["ipm.user.get", "ipm.user.list"],
          "deletionProtection": false}}
```

## 5. Reconciler (`ipm-user-reconciler`)

O estado é um cache descartável, reconstruído da mensageria. Com as guardas do loop, compara `lifecycle`, `roles` e
`deletionProtection`:

- `observed` ausente com `lifecycle present` → `create` (`Missing`);
- `roles` ou `deletionProtection` diferentes → `update` (`Drift`);
- `lifecycle absent` com o usuário presente → `delete` (`DeletionRequested`).

Os dados pessoais e a Organization não são campos gerenciados: são imutáveis e definidos na criação.

## 6. Executor (`ipm-user-executor`)

Único componente que escreve o usuário no Zitadel, com a conta `ipm-user-executor`: `ORG_USER_CREATOR` em cada organização de
cliente (cria e remove usuários, sem conceder roles) e `PROJECT_GRANT_OWNER` no Project Grant de `roles-ipm` para ela (concede
só as roles do Grant). Os dois papéis são dados pelo loop da `ipm/organization` a cada organização (decisão 0081). Valida a
mensagem, não repete um `actionId` concluído e revalida a ação contra o `desired` vigente, como em toda feature. Depois:

- **`create`:** cria o usuário humano **sem senha** na organização do `desired` (`organizationId`), com o `resourceId` como ID e
  o e-mail como nome de login; o Zitadel envia o e-mail de verificação, cuja página também define a senha. Usuário já existente
  com o mesmo ID leva a lê-lo: mesmo e-mail e mesma organização é sucesso idempotente; senão, `failed` `Rejected`. Depois deixa
  as roles e o metadado.
- **`update`:** confere que o usuário existe e é da organização do `desired`; deixa a autorização em `roles-ipm` com
  **exatamente** as roles do `desired` (cria, atualiza ou remove) e grava o metadado `deletionProtection`.
- **`delete`:** remove o usuário; ausente também é sucesso.

O Project Grant é o teto: uma role do `roles-ipm` fora do catálogo da organização é recusada pelo Zitadel
(`failed` `Rejected`, verificado pelo e2e).

## 7. Manager aplica `observed` e resultados

Como em toda feature (decisão 0072): `Ready` quando `roles` e `deletionProtection` convergem **e** a observação foi feita depois
da geração atual (`observedGeneration`); a geração confirmada vai para `observed_generation`. Remoção convergida apaga a linha e
publica `updated` com `removed`. Um `failed` marca a fase `Failed`; no limite (5) a `reconciliation` vira `suspended`.

## 8. Estados

- **Fase** (`phase`): [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg). `completed` não é `Ready`.
- **Operation:** [`state/02-operation.svg`](state/02-operation.svg).

## 9. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `ipm.user` | Manager | Receiver (view `ipm.user_v1`) |
| `ipm.user_operation` | Manager | Receiver (view `ipm.user_operation_v1`) |
| `ipm.user_action_result` | Manager | Manager (dedupe por `actionId`) |
| `ipm.user_outbox` | Manager (insere) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer, Executor (revalidação) |
| `OBSERVED` | Observer | Reconciler, Manager |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer, Manager |
| Zitadel (o usuário, a autorização em `roles-ipm` e o metadado) | Executor | Observer (leitura) |

## 10. Verificação (2026-10-21, dev)

Com os seis componentes no Compose e o Zitadel real, numa Organization preparada pelo operador:

- a suíte e2e (`tests/e2e`) cria o usuário até `Ready` (geração confirmada), troca as roles, liga a proteção e o remove pelo loop,
  e confirma que uma role fora do Grant é recusada pelo Zitadel;
- um usuário humano da Organization entrou pela aplicação `cli` (fluxo de login v2, com PKCE): o token trouxe a audience de
  `roles-ipm` e as roles dele, ligadas à organização dele; pelo gateway, ele leu o próprio registro e listou os usuários e,
  com `ipm.organization.get`, leu a Organization (o Receiver da Organization o reconheceu pelo Receiver do User). Sem
  `ipm.user.create`, a criação foi recusada (`403`).
