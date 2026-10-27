# ipm.user

O **usuário da Organization** é a pessoa que trabalha numa Organization sem ser a dona dela, no modelo das clouds: o dono (o *root*, a Account que criou a Organization) cria usuários **dentro** da própria Organization, e cada um recebe só permissões da plataforma. Decisão [`0077`](../../../.decisions/0077-ipm-user-usuarios-da-organizacao.md). É gerenciado pelo Resource Control Loop (`docs/loop/RESOURCE-CONTROL-LOOP.md`) e vive, no Zitadel, como um usuário humano da organização do cliente, com o mesmo ID (`resourceId`), e uma autorização no Project Grant de `roles-ipm` para essa organização.

Decisões que definem esta feature: `0098` (API síncrona e fim da Operation), `0096` (o loop unificado no Controller), `0097` (`desired` puro e permissões efetivas calculadas pelo Controller), `0077` (o tipo, o escopo, as permissões e o `bind`), `0076` (administrador no lugar de membro), `0028` (padrão das permissões, com a ação `bind`), `0040` (consulta entre APIs com o token de quem pede), `0043` e `0074` (proteção contra exclusão como metadado; aqui ela nasce desligada), `0072` (toda alteração percorre o loop) e `0075` (motores gerados do template). A `0096` substitui, para este tipo, a separação em Observer, Reconciler e Executor (`0063`, `0065`, `0072` e `0073`). A feature `features/ipm/organization` é o **modelo** desta estrutura.

# 1. Estado da implementação

Os papéis do loop e a CLI estão implementados e adaptados para a **API síncrona** (decisão `0098`). A suíte e2e cria o usuário numa organização real do Zitadel, troca as permissões, liga a proteção e o remove pelo loop.

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`ipm-user-api`) | API `/v1/ipm/users`: autentica, decide o escopo (operador, root ou usuário da Organization), confere o catálogo do Grant, a regra do `bind` e admite a escrita síncrona numa transação (e-mail único, cota, versão, recurso e `desired` no outbox). Contrato em `openapi.json` |
| Publisher | `publisher/` (`ipm-user-publisher`) | Publica o outbox no NATS (template, decisão 0065) |
| Controller | `controller/` (`ipm-user-controller`) | Decisão 0096: lê o `desired` do Stream `DESIRED` e, por usuário, observa o Zitadel, decide, age e reobserva numa só transação, e grava o estado e `updated` no outbox. Também consome os catálogos `DESIRED` de permission, role e group e calcula as permissões efetivas. Substitui o Reconciler, o Observer e o Executor |
| Testes e2e | `tests/e2e/` | Black-box: contrato e loop completo numa Organization preparada pelo operador |

Além dos papéis, o serviço `ipm-user-migrate` (migrações) roda e sai.

A CLI é o comando `sk ipm user create|get|list|update|protect|unprotect|delete` (`clients/cli`), com a Organization de `--organization-id` ou a ativa.

# 2. Arquitetura

![Componentes](docs/architecture/01-componentes.svg)

Fonte: [`01-componentes.mmd`](docs/architecture/01-componentes.mmd). O fluxo de dados completo está em [`docs/IPM-USER-DATA-FLOW.md`](docs/IPM-USER-DATA-FLOW.md).

# 3. Papéis e componentes

Os papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios, com o próprio papel de banco (`ipm_user_<papel>`, em `infrastructure/dev/database/bootstrap/ipm.sql`), a própria identidade no NATS e, quando usa o Zitadel, a própria conta de serviço.

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| API | `ipm-user-api` | `ipm_user_api` (lê as views; `INSERT`/`UPDATE` em `user`, `INSERT` no outbox e na idempotência; sem `DELETE`) | — | SSOT (`ipm.user*`) e outbox |
| Publisher | `ipm-user-publisher` | `ipm_user_publisher` | — | `published_at` do outbox; NATS |
| Controller | `ipm-user-controller` | `ipm_user_controller` (lê e atualiza `user`; remove a linha que convergiu; `INSERT` só no outbox) | `ipm-user-controller` (`ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na organização e `PROJECT_GRANT_OWNER` no Grant dela) | estado observado, fase, conditions e `updated` no SSOT (e o `desired` suspenso, ao suspender); o usuário no Zitadel |

## 3.1 API (`ipm-user-api`)

- Rotas sob `/v1/ipm/users`: `POST` cria (`201` + `Resource`), `GET ?organizationId=` lista, `GET /{resourceId}` lê, `PATCH /{resourceId}` altera (`200` + `Resource`) e `DELETE /{resourceId}?resourceVersion=` pede a remoção (`202`, `phase=Deleting`). Não há Operation: a convergência se lê no próprio recurso (`observedGeneration >= desiredGeneration` com `phase` `Ready` ou `Failed`; após o delete, `404`).
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-ipm`, `exp`). Cada ação exige a permissão `ipm.user.<create|get|list|update|delete>`; o operador tem `ipm.user.admin`.
- **Escopo por Organization:** o operador age em qualquer uma; o **usuário da Organization** é reconhecido pelo próprio registro no SSOT do tipo (o `resourceId` é o `sub` do token) e só age na Organization dele; a **serviceaccount** age na sua Organization (reconhecida pela API de ServiceAccount, decisão 0094); o **root** é confirmado pela API da Organization (`GET /v1/ipm/organizations/{id}` com o token de quem pede, decisão 0040). Fora do escopo, a resposta é `404`, para não revelar que existe.
- **Permissões:** só as do catálogo `grantablePermission` do contrato (`schemas/ipm/definitions.v1.schema.json`, o mesmo que a `ipm/organization` grava no Project Grant de cada Organization, decisão 0081); sem `ipm.user.bind`, quem pede só atribui ou retira permissões que ele mesmo tem (o RBAC do Kubernetes, decisão 0071). O root e o operador têm o `bind`.
- **Cota:** 5 usuários por Organization (`IPM_USER_API_API_USER_QUOTA`, valor provisório); o operador não tem cota.
- O usuário **nasce desprotegido** (exceção à 0043, registrada na 0077): `sk ipm user protect` liga a proteção, e então o `DELETE` responde `409 DeletionProtected`. Todo usuário lê o próprio registro sem permissão. `reconciliation` é do operador. `Idempotency-Key` torna as escritas repetíveis.
- **Admissão (decisão 0098):** numa transação, bloqueia a linha (`FOR UPDATE`), confere a versão (`409 Conflict`), o e-mail único (`409 NameInUse`), a cota (`403 QuotaExceeded`), o estado e a proteção (`409 DeletionProtected`); grava o recurso (`requested_by`, `correlation_id`, geração) e o `desired` no outbox. Banco indisponível é `503 StorageUnavailable` com `Retry-After`. Um `PATCH` sem mudança efetiva devolve `200` com o recurso atual, sem gravar.
- **Idempotência:** `Idempotency-Key` opcional, por solicitante, em `ipm.user_idempotency`. Mesma chave e mesmo conteúdo devolvem o recurso atual; conteúdo diferente é `422 IdempotencyKeyReused`.
- Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado.
- Ao remover, o `desired` perde `givenName`, `familyName` e `email` (`lifecycle absent` sem dados pessoais).

## 3.2 Publisher e Controller

- **Publisher:** o do template (decisão 0065), sem regra do tipo. Publica `desired` (que a API gravou) e `updated` (que o Controller gravou) do mesmo outbox.
- **Controller:** consome o Stream `DESIRED`, enfileira o `resourceId` numa fila com deduplicação e backoff e, para cada um, executa o ciclo atômico `reconcile`. Detalhes no [README do Controller](src/ipm_user/controller/README.md) e em [`docs/IPM-USER-DATA-FLOW.md`](docs/IPM-USER-DATA-FLOW.md), seção 4.
  - **Decisão:** campos gerenciados `lifecycle`, as permissões efetivas (calculadas do catálogo a partir de `roles` e `groups`, decisão 0097) e `deletionProtection`; a Organization e os dados pessoais são imutáveis.
  - **Observação:** lê o usuário (`userState`, `initial` até a senha ser definida, e `emailVerified`), as permissões dele em `roles-ipm` e o metadado `deletionProtection`. `absent` só com o `404` do usuário exato; qualquer falha é `unknown`. Não grava dados pessoais no `observed`.
  - **Ação:** cria o usuário humano **sem senha** na organização do cliente (o Zitadel envia o e-mail de verificação, que define a senha), deixa a autorização em `roles-ipm` com **exatamente** as permissões efetivas e grava o metadado; remove o usuário no `delete`. O Project Grant é o teto: uma permissão fora dele é recusada pelo Zitadel.

## 3.3 Um projeto, uma imagem, três papéis (decisões 0063, 0096 e 0098)

```text
src/ipm_user/
  common/      igual em todos os papéis (template, decisão 0064), exceto resource.py e contracts/generated.py
  api/  publisher/  controller/    (cada um com o seu README)
tests/
  common/  api/  publisher/  controller/    (unit, contract e integration)
  e2e/                                      (projeto à parte, black-box)
migrations/    SQL da API e do Controller, aplicado pelo serviço ipm-user-migrate
```

A convergência e os handlers do Manager e o domínio comum do Receiver vêm do template (perfis `receiver-http`, `manager-handlers` e `identity-metadata`, decisão 0075): altere o modelo em `templates/feature/`, não a cópia.

## 3.5 Estrutura interna dos papéis

| Papel | Pastas | README |
|---|---|---|
| Receiver | `auth/`, `domain/` (`access.py`: catálogo e `bind`), `http/`, `store/`, `transport/` (Receiver da Organization) | [`receiver`](src/ipm_user/receiver/README.md) |
| Manager | `domain/`, `handlers/`, `store/`, `transport/` | [`manager`](src/ipm_user/manager/README.md) |
| Publisher | `domain/`, `outbox/` | [`publisher`](src/ipm_user/publisher/README.md) |
| Controller | `domain/` (`decision`, `convergence`), `drivers/` (`user`, `authorization`, `metadata`, `identity`), `engine/` (fila, observação, ação, ciclo `reconcile`), `store/` | [`controller`](src/ipm_user/controller/README.md) |

## 3.6 Testes e2e (`tests/e2e`)

Suíte black-box (decisão 0017): fala só com o gateway, o NATS e o SSOT (limpeza), numa Organization preparada pelo operador (`CONFORMANCE_ORGANIZATION_ID`). Ver [`tests/e2e/README.md`](tests/e2e/README.md).

# 4. Fluxos

| Fluxo | Diagrama |
|---|---|
| Criar um usuário, do `POST` ao usuário no Zitadel | [`flow/01-criar-usuario`](docs/flow/01-criar-usuario.svg) |
| Erros antes de entrar no loop e recusas do Manager | [`flow/02-validacao-e-borda`](docs/flow/02-validacao-e-borda.svg) |
| Alterar as roles e remover | [`flow/03-alterar-roles-e-remover`](docs/flow/03-alterar-roles-e-remover.svg) |
| Falhas no Manager, na mensageria e no Publisher | [`flow/04-falhas-no-manager-e-mensageria`](docs/flow/04-falhas-no-manager-e-mensageria.svg) |
| Falhas na reconciliação e reinício do estado | [`flow/05-falhas-na-reconciliacao`](docs/flow/05-falhas-na-reconciliacao.svg) |
| Falhas na ação do provedor | [`flow/06-falhas-no-executor`](docs/flow/06-falhas-no-executor.svg) |

# 5. Estados

- Fase do recurso (`phase`): [`state/01-fase-do-recurso`](docs/state/01-fase-do-recurso.svg).
- Operation (`operationStatus`): [`state/02-operation`](docs/state/02-operation.svg).

# 6. Mensageria

O tipo **não tem** o Stream `REQUESTED` (decisão 0098): a API grava o `desired` no outbox na própria admissão, com `emitter: api`. O `updated` do Controller continua com `emitter: manager`. O modelo geral está em [`docs/messaging/NATS.md`](../../../docs/messaging/NATS.md).

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `DESIRED` | `manager.desired.ipm.user.>` | `ipm-user-controller-desired-<instância>` | Controller |
| `DESIRED` | `manager.desired.ipm.{permission,role,group}.>` | `ipm-user-controller-{permissions,roles,groups}-<instância>` e a API para o catálogo de acesso | Controller e API |

# 7. Contratos

Em `schemas/ipm/user/` (e `schemas/common/`), com o índice `schemas/ipm.user.index.json`: `definitions`, `desired`, `observed`, `api-create-request`, `api-update-request`, `resource` e `resource-list`. Os modelos Pydantic são gerados (`uv run datamodel-codegen`, decisão 0012) e conferidos por teste de contrato. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado por `uv run python -m ipm_user.api.http.openapi > openapi.json` e conferido por teste.

# 8. Segurança e privacidade

- **Só permissões da plataforma:** o usuário nunca recebe papel nativo do Zitadel (`ORG_OWNER`, `ORG_USER_CREATOR`...): eles permitiriam agir pelo console, fora do loop (decisão 0077).
- **O Grant é o teto, duas vezes:** a API recusa a permissão fora do catálogo e do módulo `ipm`, e o Zitadel a permissão fora do Project Grant da organização (verificado pelo e2e).
- **`bind`:** sem ele, ninguém concede mais do que tem, nem retira o que não tem.
- **Escopo:** um usuário só age na própria Organization; o reconhecimento é pelo registro no SSOT, e o do root, pela API da Organization com o token de quem pede.
- **Sem senha na plataforma:** o usuário define a senha no Zitadel, pelo e-mail de ativação; ela nunca passa por CLI, API, SSOT nem NATS.
- **Dados pessoais:** `givenName`, `familyName` e `email` são `confidential`: ficam no `desired` (SSOT e Stream `DESIRED`) enquanto o usuário existe, saem dele na remoção e nunca vão para logs, erros ou métricas. O `observed` não os traz.
- **Menor privilégio no Zitadel:** o Controller, única identidade do tipo no provedor, só tem `ORG_USER_CREATOR`, `ORG_OWNER_VIEWER` e `PROJECT_GRANT_OWNER` nas organizações de cliente; não tem papel na `core`, na `register` ou na instância (conferido pela suíte de conformidade de identidade).

## 8.1 Identidades e privilégios por papel

| Papel | Banco | NATS | Zitadel |
|---|---|---|---|
| API | `SELECT` nas views; `INSERT` e `UPDATE` em `user`; `INSERT` no outbox e em `user_idempotency` | lê os catálogos em `DESIRED` | só valida tokens (JWKS) |
| Publisher | `SELECT` no outbox e `UPDATE (published_at)` | publica `desired` e `updated` | — |
| Controller | `SELECT`, `UPDATE` e `DELETE` em `user`; `INSERT` no outbox | lê `desired` | `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na organização; `PROJECT_GRANT_OWNER` no Grant dela |

# 9. Configuração, execução e testes

Variáveis `IPM_USER_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias: a senha do NATS, as senhas dos papéis do banco, a audience do Receiver e o ID do projeto `roles-ipm` (Controller). As chaves das contas de serviço são arquivos montados do volume `identity-bootstrap`.

**Toda Organization já nasce preparada** pelo loop da `ipm/organization` (decisão 0081): o Project Grant de `roles-ipm` com o catálogo e os papéis do Controller do User nela. As anteriores à decisão são preparadas pelo rollout na partida do Manager da Organization.

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes do User
cd features/ipm/user && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest
# 4. Testes e2e (stack no ar e uma Organization preparada): ver tests/e2e/README.md
```

# 10. Limitações e pendências

- O catálogo do Grant é o mesmo para todas as Organizations e muda só com o contrato (decisão 0081): mudar o enum `grantablePermission`, regerar os modelos das duas features e implantar.
- O root recebe as permissões `ipm.user.*` pelo catálogo do SUM ao habilitar o `ipm` (`SUM_SERVICE_MANAGER_CATALOG_PERMISSIONS`); quem habilitou antes dessa versão precisa desabilitar e habilitar de novo.
- A cota (5) é provisória, para testar o mecanismo.
- O e-mail é imutável: a troca é pelo fluxo do Zitadel, e o SSOT não acompanha.
- A Operation não vira `failed`: a falha aparece na fase `Failed` do usuário.

# 11. Banco de dados (SSOT do usuário da Organization)

## 11.1 Entidade e relacionamento

![ER físico](docs/database/01-er-fisico.svg)

Fonte: [`01-er-fisico.mmd`](docs/database/01-er-fisico.mmd).

## 11.2 Tabelas

| Tabela | Conteúdo | Quem grava |
|---|---|---|
| `ipm.user` | Uma linha por usuário: intenção, observado, fase, geração confirmada | API (admissão síncrona); Controller (observado, fase, conditions, geração confirmada; remove a linha ao convergir a remoção) |
| `ipm.user_idempotency` | Idempotência das admissões | API |
| `ipm.user_outbox` | Mensagens `desired` e `updated` à espera de publicação, com o `traceparent` | API insere o `desired`; Controller insere o `updated`; Publisher marca `published_at` |

A migração [`0001-user.sql`](migrations/0001-user.sql) nasce com o estado atual das migrações do modelo: `observed_generation` (decisão 0072), o motivo `protected` (decisão 0043) e o `traceparent` do outbox (decisão 0055). A migração `0007-user-api.sql` remove a tabela `user_operation` e introduz a API síncrona (decisão 0098).

## 11.3 O que cada coluna `jsonb` guarda

- `user.desired`: `lifecycle`, `organizationId`, `roles`, `groups`, `deletionProtection` e, enquanto `present`, `givenName`, `familyName` e `email`.
- `user.observed`: `emailVerified`, `userState`, `permissions` (as do Zitadel), `effectivePermissions` (as calculadas pelo Controller) e `deletionProtection`.

## 11.4 Índices e restrições

- `user_organization` (sobre `desired ->> 'organizationId'` e `desired ->> 'email'`): a lista e a cota por Organization e o e-mail único nela, conferidos pelo Manager sob trava consultiva, e não por restrição única.
- `user_observed_generation_check`: `observed_generation` nula ou entre 1 e `desired_generation`.

## 11.5 Consultas úteis (dev)

```sql
-- Usuários por Organization e fase
SELECT desired ->> 'organizationId' AS organizacao, phase, count(*) FROM ipm.user GROUP BY 1, 2 ORDER BY 1, 2;

-- Geração pedida e confirmada
SELECT resource_id, desired_generation, observed_generation, phase FROM ipm.user ORDER BY updated_at DESC LIMIT 20;
```
