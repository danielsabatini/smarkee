# ipm.organization

A **Organization** é a unidade de isolamento da plataforma (`.decisions/0006-organization-como-unidade-de-isolamento.md`): um recurso do módulo `ipm` (`.decisions/0016-organization-no-modulo-ipm.md`), criado por um usuário registrado (a Account, do módulo `core`), que passa a ser o dono dela. É gerenciada pelo Resource Control Loop (`docs/loop/RESOURCE-CONTROL-LOOP.md`, seção 46) e vive, no Zitadel, como uma organização com o mesmo ID (`resourceId`).

Decisões que definem esta feature: `0006` e `0016` (o que é a Organization e onde mora), `0010` (roles, dono, cota e acesso no Zitadel), `0015` (componentes por papel), `0017` (estrutura interna e testes e2e), `0018` (partições e saúde), `0019` (Publisher), `0038` (refeita a partir da Account: só a organização no Zitadel), `0096` (o loop de reconciliação unificado no Controller, que substituiu o Observer, o Reconciler e o Executor) e `0098` (API síncrona na admissão e fim da Operation). A feature `features/core/account` é o **modelo** desta estrutura.

# 1. Estado da implementação

Os três papéis do loop e a CLI estão implementados e adaptados para a **API síncrona** (decisão `0098`). A suíte e2e cria, renomeia, desativa, reativa e remove a organização no Zitadel real, com falha de componente.

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`ipm-organization-api`) | API `/v1/ipm/organizations`: autentica, confere a permissão, o e-mail verificado e a cota, reconhece os usuários da Organization e só remove a Organization vazia (pelo User), admite a escrita síncrona numa transação (unicidade global de nome sob trava consultiva, cota por dono, geração, recurso e `desired` no outbox). Contrato em `openapi.json` |
| Publisher | `publisher/` (`ipm-organization-publisher`) | Publica o outbox no NATS, com trava de sessão, envelope estrito e `Nats-Msg-Id` (decisão 0019) |
| Controller | `controller/` (`ipm-organization-controller`) | Decisão 0096: por Organization, observa o Zitadel, decide, age e reobserva numa só transação, e grava o estado e o `updated` no outbox. Substitui o Reconciler, o Observer e o Executor |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo e caos (os três papéis de runtime) |

Além dos papéis, o serviço `ipm-organization-migrate` (migrações) roda e sai.

A CLI é o comando `sk ipm organization create|get|list|update|protect|unprotect|delete` (`clients/cli`).

# 2. Arquitetura

![Componentes](docs/architecture/01-componentes.svg)

Fonte: [`01-componentes.mmd`](docs/architecture/01-componentes.mmd) (diagrama ainda no modelo anterior à decisão 0096; ver a nota da seção 4). O fluxo de dados completo está em [`docs/IPM-ORGANIZATION-DATA-FLOW.md`](docs/IPM-ORGANIZATION-DATA-FLOW.md).

# 3. Papéis e componentes

Os papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios: cada papel tem o próprio papel de banco (`ipm_organization_<papel>`, em `infrastructure/dev/database/bootstrap/ipm.sql`), a própria identidade no NATS e, quando usa o Zitadel, a própria conta de serviço. O código igual em todos fica em `common/`, e nenhum papel importa outro.

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| API | `ipm-organization-api` | `ipm_organization_api` (lê as views; `INSERT`/`UPDATE` em `organization`, `INSERT` no outbox e na idempotência; sem `DELETE`) | — | SSOT (`ipm.organization*`) e outbox |
| Publisher | `ipm-organization-publisher` | `ipm_organization_publisher` | — | `published_at` do outbox; NATS |
| Controller | `ipm-organization-controller` | `ipm_organization_controller` (lê e atualiza `organization`; remove a linha que convergiu; `INSERT` só no outbox) | `ipm-organization-controller` (`IAM_ORG_MANAGER`, de instância) | estado observado, fase, conditions no SSOT; `updated` no outbox; a organização no Zitadel |

## 3.1 API (`ipm-organization-api`)

- Rotas sob `/v1/ipm/organizations`: `POST` cria (`201` + `Resource`), `GET` lista, `GET /{resourceId}` lê, `PATCH /{resourceId}` altera (`200` + `Resource`) e `DELETE /{resourceId}?resourceVersion=` remove (`202`, `phase=Deleting`). Não há Operation: a convergência se lê no próprio recurso (`observedGeneration >= desiredGeneration` com `phase` `Ready` ou `Failed`; após o delete, `404`).
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-ipm`, `exp`). O dono é o `sub`: nunca vem do corpo, que só tem `name`. Cada ação exige a permissão `ipm.organization.<create|get|list|update|delete>`. Para criar, o solicitante precisa de **e-mail verificado** e de cota (`IPM_ORGANIZATION_API_API_ORGANIZATION_QUOTA`, padrão 1); o operador (`ipm.organization.admin`) não tem cota.
- O dono altera o `name` e a proteção contra exclusão (`deletionProtection`); `platformAccess` e `reconciliation` são do operador. A Organization **nasce protegida** (decisão 0043): o `DELETE` responde `409 DeletionProtected` até um `PATCH` com `deletionProtection: false`; alterar só a proteção percorre o loop como qualquer alteração e conclui quando a observação confirma a nova geração (decisão 0072). Registro sem o campo vale como protegido. Uma Organization de outro dono responde `404`, para não revelar que existe. `Idempotency-Key` torna o `POST`, o `PATCH` e o `DELETE` repetíveis.
- **Usuários da Organization** (`ipm.user`, decisão 0077): além do dono e do operador, um usuário da Organization age nela com as permissões `ipm.organization.get|list|update`. A API o reconhece perguntando à API do User de que Organization ele é (`GET /v1/ipm/users/{sub}`, o próprio registro, com o token de quem pede; decisão 0040). O dono é reconhecido antes, sem consulta. A lista de quem não é dono de nenhuma é a Organization de que ele é usuário.
- **Só vazia:** o `DELETE` pergunta à API do User se a Organization ainda tem usuários (`GET /v1/ipm/users?organizationId=`): com usuários, `409 ResourcesAttached`; sem resposta conclusiva, `503 UsersUnavailable` (repetível) ou `409 ResourcesNotVerifiable`. A remoção no Zitadel apagaria os usuários junto.
- **Admissão (decisão 0098):** numa transação atômica, adquire travas consultivas por nome e por dono, confere unicidade de nome (`409 NameInUse`), cota (`403 QuotaExceeded`), versão (`409 Conflict`) e proteção (`409 DeletionProtected`); grava o recurso (`requested_by`, `correlation_id`, geração) e o `desired` no outbox.
- **Idempotência:** `Idempotency-Key` opcional, por solicitante, em `ipm.organization_idempotency`. Mesma chave e mesmo conteúdo devolvem o recurso atual; conteúdo diferente é `422 IdempotencyKeyReused`.
- Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado.

## 3.2 Publisher (`ipm-organization-publisher`)

- Lê o outbox em ordem de `sequence`, valida o envelope de forma estrita, acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.ipm.organization.<resourceId>.changed` (e `updated`), com `Nats-Msg-Id` igual ao `messageId`. Marca `published_at` depois da confirmação.
- Uma instância ativa por trava consultiva de sessão. Recusa permanente (ou envelope inválido) mantém a mensagem pendente, registra `ERROR` e tira o Publisher de `ready`, sem derrubar o processo (decisão 0018).

## 3.3 Controller (`ipm-organization-controller`)

Decisão [`0096`](../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md), no padrão do Kubernetes Controller (Informer + Workqueue, AGENTS.md §2.7). Um único processo observa, decide, age e reobserva a Organization, **numa só transação**, e grava o estado convergido e o `updated` no outbox (o Publisher o entrega). O ciclo completo está no [fluxo de dados](docs/IPM-ORGANIZATION-DATA-FLOW.md), seção 4.

- **Entrada:** o Informer consome `manager.desired.ipm.organization.>` (Stream `DESIRED`, consumer por instância `ipm-organization-controller-desired-<instância>`) e enfileira o `resourceId` numa Workqueue com deduplicação e *backoff* exponencial com *jitter*; uma reavaliação periódica (padrão 300 s) enfileira todas as Organizations `active` da partição, para detectar *drift* feito fora do loop. Cada réplica cuida só da sua partição (`hash(resourceId) mod count`).
- **Ciclo `reconcile(resourceId)`:** com a linha bloqueada (`FOR UPDATE`), lê a organização, os metadados e o preparo para os usuários no Zitadel, decide com a função pura `decide(desired, observed)` (`create`, `update` ou `delete`; `unknown` nunca autoriza ação), executa a ação idempotente, reobserva e grava `observed`, fase, conditions e `updated`. Os campos comparados são `lifecycle`, `name`, `platformAccess`, `deletionProtection` e `userAccess`.
- **Escrita no Zitadel:** é a única identidade do tipo no provedor. Escreve a organização e o **preparo para os usuários** (decisão 0081): o Project Grant de `roles-ipm` com o catálogo `grantablePermission` do contrato, e as permissões das contas dos tipos `ipm/user` e `ipm/serviceaccount` (decisão 0094), só com o que falta e só com `platformAccess = granted`. Não cria usuários nem autoriza o dono. O ID da organização é o `resourceId`, então repetir a criação não duplica.
- **Falhas:** erro transitório do provedor devolve a Organization à fila com *backoff*; a falha da ação conta no `failure_count` e, no limite (`loop.failure_limit`, padrão 5), a `reconciliation` vira `suspended` e um `desired` suspenso vai ao outbox. Não há registro por `actionId`: repetir o ciclo é seguro porque a decisão é recalculada do estado real e as ações são idempotentes.
- **Prazos:** `loop.progress_deadline_seconds` (padrão 300) gera a condition `Progressing` `False` (`ProgressDeadlineExceeded`); uma Organization `unknown` além do prazo recebe `ObservationStale` (decisão 0090).
- Não confia em ninguém para decidir: o `desired` vigente é lido do SSOT dentro da transação, não de uma mensagem.

## 3.4 Um projeto, uma imagem, três papéis (decisões 0063, 0096 e 0098)

`ipm.organization` é **um projeto** (`pyproject.toml`, `uv.lock`, `Dockerfile`) e **uma imagem** (`smarkee-ipm-organization`), que contém o código dos três papéis. Cada papel roda como **contêiner próprio**, escolhido pelo `command` (`ipm-organization-api`, `-publisher` e `-controller`), com as suas próprias variáveis, segredos, papel de banco e identidade no NATS. Ter o código de um papel na imagem de outro não dá privilégio: ele vem da credencial.

```text
src/ipm_organization/
  common/      o que é igual em todos os papéis: settings, messaging, lifecycle, database, identity
               (token da conta de serviço), ports, resource (módulo, tipo e versão), contracts/
               (modelos gerados, base e envelope), logging_config, ids e http/health
  api/  publisher/  controller/    (cada um com o seu README)
tests/
  common/  api/  publisher/  controller/    (unit, contract e integration)
  e2e/                                      (projeto à parte, black-box)
migrations/    SQL da API e do Controller, aplicado pelo serviço ipm-organization-migrate
```

Um papel nunca importa outro (`tests/common/unit/test_role_isolation.py`); só o `common/`. Comandos de desenvolvimento, na raiz da feature: `uv sync`, `uv run ruff check . && uv run ruff format --check . && uv run pyright` e `uv run pytest` (a suíte e2e, em `tests/e2e`, tem projeto próprio).

## 3.5 Estrutura interna dos papéis

Cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro e sem I/O (decisão 0017): a dependência vai em um sentido só (`main → orquestração → domain`), e o `domain` nunca importa um adaptador (`tests/common/unit/test_domain_isolation.py` garante isso para todos os papéis). As pastas de cada papel:

| Papel | Pastas | README |
|---|---|---|
| API | `auth/`, `domain/`, `http/`, `store/`, `transport/` (API do User, ServiceAccount e BSM) | [`api`](src/ipm_organization/api/README.md) |
| Publisher | `domain/`, `outbox/` | [`publisher`](src/ipm_organization/publisher/README.md) |
| Controller | `domain/` (`decision`, `convergence`), `drivers/` (`organization`, `metadata`, `user_access`, `identity`), `engine/` (fila, observação, ação, ciclo `reconcile`), `store/` | [`controller`](src/ipm_organization/controller/README.md) |

A saúde (`/health/*`) é de `common/http/health.py`, igual em todos os papéis.

## 3.6 Testes e2e (`tests/e2e`)

Suíte black-box (decisão 0017): fala só com o gateway, o NATS, o SSOT (limpeza) e o Docker (caos), e valida contra os schemas. Ver [`tests/e2e/README.md`](tests/e2e/README.md).

# 4. Fluxos

| Fluxo | Diagrama |
|---|---|
| Criar uma Organization, do `POST` à organização no Zitadel | [`flow/01-criar-organization`](docs/flow/01-criar-organization.svg) |
| Erros antes de entrar no loop e recusas | [`flow/02-validacao-e-borda`](docs/flow/02-validacao-e-borda.svg) |
| Atualizar (renomear) e remover | [`flow/03-atualizar-e-remover`](docs/flow/03-atualizar-e-remover.svg) |
| Falhas na mensageria e no Publisher | [`flow/04-falhas-no-manager-e-mensageria`](docs/flow/04-falhas-no-manager-e-mensageria.svg) |
| Falhas na reconciliação e reinício do estado | [`flow/05-falhas-na-reconciliacao`](docs/flow/05-falhas-na-reconciliacao.svg) |
| Falhas na ação do provedor | [`flow/06-falhas-no-executor`](docs/flow/06-falhas-no-executor.svg) |

O fluxo de dados completo, passo a passo, está em [`docs/IPM-ORGANIZATION-DATA-FLOW.md`](docs/IPM-ORGANIZATION-DATA-FLOW.md).

> **Diagramas pendentes (decisão 0096 e 0098):** os SVGs e os `.mmd` de `flow/`, `architecture/` e `database/` ainda mostram o modelo anterior com Receiver, Manager e Operation. O texto é o vigente.

# 5. Estados

- Fase do recurso (`phase`): [`state/01-fase-do-recurso`](docs/state/01-fase-do-recurso.svg).

# 6. Mensageria

Este tipo só usa o Stream `DESIRED` (decisões 0096 e 0098): os Streams `REQUESTED`, `OBSERVED`, `ACTION` e `RESULT` não existem para ele. O modelo geral está em [`docs/messaging/NATS.md`](../../../docs/messaging/NATS.md).

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `DESIRED` | `manager.desired.ipm.organization.>` | `ipm-organization-controller-desired-<instância>` | Controller |

Os consumers do Controller não têm manifesto: cada instância cria os próprios consumers de estado, com nome único por execução, `DeliverLastPerSubject` e `inactive_threshold`, e reconstrói o estado da mensageria (`docs/messaging/NATS.md` §7.4).

# 7. Contratos

Os contratos estão em `schemas/ipm/organization/` (e `schemas/common/`), com o índice `schemas/ipm.organization.index.json`: `desired`, `observed`, `api-create-request`, `api-update-request`, `resource` e `resource-list`. Os modelos Pydantic de cada componente são gerados (`uv run datamodel-codegen`, decisão 0012) e conferidos por teste de contrato na API. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado por `uv run python -m ipm_organization.api.http.openapi` e conferido por teste.

# 8. Segurança e privacidade

- **Dono pelo token:** o `ownerAccountId` é o `sub` do token. O corpo do `POST` só aceita `name`; qualquer outro campo é recusado pelo contrato. O dono vive só no `desired` (no SSOT e na mensageria), nunca no Zitadel nem nas respostas ao usuário.
- **Sem dados pessoais:** a Organization guarda só IDs e o nome. Não há e-mail, nome de pessoa nem token no banco, nas mensagens ou nos logs.
- **Menor escrita:** o Controller escreve só a organização e o preparo dela para os usuários (decisão 0081), sem privilégio a mais: o `IAM_ORG_MANAGER` já tem `project.grant.write` e `org.member.write`. O papel `IAM_ORG_MANAGER` é de instância (o Zitadel não tem papel padrão menor para criar e listar organizações). **Exceção deliberada** (decisão 0060): fica assim em todos os ambientes, até o Zitadel oferecer um papel padrão menor. Com o Controller, a mesma conta lê e escreve: a separação de leitura e escrita que o Observer e o Executor davam deixou de existir (decisão 0096), e a lacuna está declarada em `docs/platform/IMPLEMENTATION-STATUS.md`.
- **Última barreira:** o Controller não decide a partir de mensagem: lê o `desired` vigente do SSOT dentro da transação, com a linha bloqueada, e uma Organization com a `reconciliation` `suspended` não é tocada.
- **Nomes:** nomes reservados e repetidos são recusados antes de o pedido chegar ao Zitadel; um nome já usado só no Zitadel (e não reservado) faz a ação falhar com `Rejected` no Controller.
- **Erros e logs:** nenhuma resposta ou log repete o valor enviado, senhas ou tokens; as configurações escondem os segredos (`SecretStr`).

## 8.1 Identidades e privilégios por papel

| Papel | Banco | NATS | Zitadel |
|---|---|---|---|
| API | `SELECT` nas views; `INSERT` e `UPDATE` em `organization`; `INSERT` no outbox e em `organization_idempotency` | — | só valida tokens (JWKS) |
| Publisher | `SELECT` no outbox e `UPDATE (published_at)` | publica `desired` e `updated` | — |
| Controller | `SELECT`, `UPDATE` e `DELETE` em `organization`; `INSERT` no outbox | lê `desired` | cria, altera, ativa, desativa e remove organizações; cria e ajusta o Grant e os papéis das contas `ipm/user` e `ipm/serviceaccount` nelas, e lê tudo isso; `IAM_ORG_MANAGER` |

Os privilégios estão em `migrations/0001-organization.sql`, `0007-organization-controller.sql`, `0008-organization-remove-action-result.sql` e `0009-organization-api.sql`.

# 9. Configuração, execução e testes

Variáveis `IPM_ORGANIZATION_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros de cada papel, a ordem de precedência (linha de comando → ambiente → `config.toml` → arquivos de segredo → default) e um exemplo de execução por papel estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias: a senha do NATS (Publisher, Controller), as senhas dos papéis do banco (API, Publisher, Controller), a audience da API e o ID do projeto `roles-ipm` (Controller). A chave da conta de serviço do Zitadel do Controller é um arquivo montado do volume `identity-bootstrap`.
