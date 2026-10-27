# ipm.organization

A **Organization** é a unidade de isolamento da plataforma (`.decisions/0006-organization-como-unidade-de-isolamento.md`): um recurso do módulo `ipm` (`.decisions/0016-organization-no-modulo-ipm.md`), criado por um usuário registrado (a Account, do módulo `core`), que passa a ser o dono dela. É gerenciada pelo Resource Control Loop (`docs/loop/RESOURCE-CONTROL-LOOP.md`, seção 46) e vive, no Zitadel, como uma organização com o mesmo ID (`resourceId`).

Decisões que definem esta feature: `0006` e `0016` (o que é a Organization e onde mora), `0010` (roles, dono, cota e acesso no Zitadel), `0015` (componentes por papel), `0017` (estrutura interna e testes e2e), `0018` (partições e saúde), `0019` (Publisher), `0020` (Receiver), `0038` (refeita a partir da Account: só a organização no Zitadel) e `0096` (o loop de reconciliação unificado no Controller, que substituiu o Observer, o Reconciler e o Executor). A feature `features/core/account` é o **modelo** desta estrutura.

# 1. Estado da implementação

Os quatro papéis do loop e a CLI estão implementados e rodam no dev (Compose). A suíte e2e cria, renomeia, desativa, reativa e remove a organização no Zitadel real, com falha de componente.

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`ipm-organization-receiver`) | API `/v1/ipm/organizations`: autentica, confere a permissão, o e-mail verificado e a cota, reconhece os usuários da Organization e só remove a Organization vazia (pelo Receiver do User), publica `requested`. Contrato em `openapi.json` |
| Manager | `manager/` (`ipm-organization-manager`) | Consome `requested` e o catálogo `DESIRED` de permission; nomes reservados, unicidade e cota por dono na unidade atômica; faz o rollout do `userAccess` |
| Publisher | `publisher/` (`ipm-organization-publisher`) | Publica o outbox no NATS, com trava de sessão, envelope estrito e `Nats-Msg-Id` (decisão 0019) |
| Controller | `controller/` (`ipm-organization-controller`) | Decisão 0096: por Organization, observa o Zitadel, decide, age e reobserva numa só transação, e grava o estado e o `updated` no outbox. Substitui o Reconciler, o Observer e o Executor |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo e caos (os quatro papéis de runtime) |

Além dos papéis, dois serviços rodam e saem: `ipm-organization-migrate` (migrações) e `ipm-organization-consumer` (consumer de `requested` do Manager).

A CLI é o comando `sk ipm organization create|get|list|update|delete` (`clients/cli`).

# 2. Arquitetura

![Componentes](docs/architecture/01-componentes.svg)

Fonte: [`01-componentes.mmd`](docs/architecture/01-componentes.mmd) (diagrama ainda no modelo anterior à decisão 0096; ver a nota da seção 4). O fluxo de dados completo está em [`docs/IPM-ORGANIZATION-DATA-FLOW.md`](docs/IPM-ORGANIZATION-DATA-FLOW.md).

# 3. Papéis e componentes

Os papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios: cada papel tem o próprio papel de banco (`ipm_organization_<papel>`, em `infrastructure/dev/database/bootstrap/ipm.sql`), a própria identidade no NATS e, quando usa o Zitadel, a própria conta de serviço. O código igual em todos fica em `common/`, e nenhum papel importa outro.

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| Receiver | `ipm-organization-receiver` | `ipm_organization_receiver` (só leitura das views) | — | `requested` no NATS |
| Manager | `ipm-organization-manager` | `ipm_organization_manager` | — | SSOT (`ipm.organization*`: admissão dos pedidos) e outbox |
| Publisher | `ipm-organization-publisher` | `ipm_organization_publisher` | — | `published_at` do outbox; NATS |
| Controller | `ipm-organization-controller` | `ipm_organization_controller` (lê e atualiza `organization` e `organization_operation`; remove a linha que convergiu; `INSERT` só no outbox) | `ipm-organization-controller` (`IAM_ORG_MANAGER`, de instância) | estado observado, fase, conditions e Operations no SSOT; `updated` no outbox; a organização no Zitadel |

## 3.1 Receiver (`ipm-organization-receiver`)

- Rotas sob `/v1/ipm/organizations`: `POST` cria, `GET` lista, `GET /{resourceId}` lê, `PATCH /{resourceId}` altera, `DELETE /{resourceId}?resourceVersion=` remove e `GET /{resourceId}/operations/{operationId}` acompanha a Operation.
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-ipm`, `exp`). O dono é o `sub`: nunca vem do corpo, que só tem `name`. Cada ação exige a permissão `ipm.organization.<create|get|list|update|delete>`. Para criar, o solicitante precisa de **e-mail verificado** e de cota (`IPM_ORGANIZATION_RECEIVER_API_ORGANIZATION_QUOTA`, padrão 1); o operador (`ipm.organization.admin`) não tem cota.
- O dono altera o `name` e a proteção contra exclusão (`deletionProtection`); `platformAccess` e `reconciliation` são do operador. A Organization **nasce protegida** (decisão 0043): o `DELETE` responde `409 DeletionProtected` até um `PATCH` com `deletionProtection: false`; alterar só a proteção percorre o loop como qualquer alteração e conclui quando a observação confirma a nova geração (decisão 0072). Registro sem o campo vale como protegido. Uma Organization de outro dono responde `404`, para não revelar que existe. `Idempotency-Key` torna o `POST`, o `PATCH` e o `DELETE` repetíveis.
- **Usuários da Organization** (`ipm.user`, decisão 0077): além do dono e do operador, um usuário da Organization age nela com as permissões `ipm.organization.get|list|update`. O Receiver o reconhece perguntando ao Receiver do User de que Organization ele é (`GET /v1/ipm/users/{sub}`, o próprio registro, com o token de quem pede; decisão 0040). O dono é reconhecido antes, sem consulta. A lista de quem não é dono de nenhuma é a Organization de que ele é usuário.
- **Só vazia:** o `DELETE` pergunta ao Receiver do User se a Organization ainda tem usuários (`GET /v1/ipm/users?organizationId=`): com usuários, `409 ResourcesAttached`; sem resposta conclusiva, `503 UsersUnavailable` (repetível) ou `409 ResourcesNotVerifiable`. A remoção no Zitadel apagaria os usuários junto. O endereço do Receiver do User é `IPM_ORGANIZATION_RECEIVER_PEERS_USERS_URL`.
- Só lê o SSOT, pelas views `ipm.organization_v1` e `ipm.organization_operation_v1`. Não expõe `/docs` nem `/openapi.json`: o contrato descritivo é o arquivo versionado `openapi.json`, conferido por teste. Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado.

## 3.2 Manager (`ipm-organization-manager`)

- Admite os pedidos no SSOT (`ipm.organization`, `ipm.organization_operation`) e no outbox: cria a linha, grava o novo `desired` e registra a Operation. Quem grava o estado observado, a fase e a conclusão das Operations é o Controller (decisão 0096).
- Consome `requested` (criar, alterar e remover) e o catálogo `DESIRED` de permission (`manager.desired.ipm.permission.>`, que atualiza o `grantPermissions`, decisão 0083). Aceita ou recusa com motivo (`conflict`, `validation`, `not_found`, `protected`): o `delete` de uma Organization protegida (`deletionProtection`, decisão 0043) é `protected`; nome reservado, nome já usado e cota por dono esgotada são `validation`; a unicidade e a cota são conferidas na mesma unidade atômica, sob trava consultiva por nome e por dono.
- Só insere no outbox: a publicação é do Publisher. ACK depois do `COMMIT`; falha transitória do banco é `RETRY`; mensagem fora do contrato (inclusive de outra versão `MAJOR`) é `TERM`.
- Na partida, antes dos consumers, faz o **rollout do `userAccess`** (decisão 0081): cada Organization cujo `desired` difere do `userAccess` de agora ganha uma geração nova. As contas `ipm-user-*` e `ipm-serviceaccount-*` (settings `user_access.*`) são **contas de outras features que recebem papéis em cada Organization**, configuradas no Manager; não são papéis desta feature.
- Não consome `observed` nem resultados de ação: a fase, as Operations e a remoção da linha convergida são do Controller.

## 3.3 Publisher (`ipm-organization-publisher`)

- Lê o outbox em ordem de `sequence`, valida o envelope de forma estrita, acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.ipm.organization.<resourceId>.changed` (e `updated`), com `Nats-Msg-Id` igual ao `messageId`. Marca `published_at` depois da confirmação.
- Uma instância ativa por trava consultiva de sessão. Recusa permanente (ou envelope inválido) mantém a mensagem pendente, registra `ERROR` e tira o Publisher de `ready`, sem derrubar o processo (decisão 0018).

## 3.4 Controller (`ipm-organization-controller`)

Decisão [`0096`](../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md), no padrão do Kubernetes Controller (Informer + Workqueue, AGENTS.md §2.7). Um único processo observa, decide, age e reobserva a Organization, **numa só transação**, e grava o estado convergido e o `updated` no outbox (o Publisher o entrega). O ciclo completo está no [fluxo de dados](docs/IPM-ORGANIZATION-DATA-FLOW.md), seção 4.

- **Entrada:** o Informer consome `manager.desired.ipm.organization.>` (Stream `DESIRED`, consumer por instância `ipm-organization-controller-desired-<instância>`) e enfileira o `resourceId` numa Workqueue com deduplicação e *backoff* exponencial com *jitter*; uma reavaliação periódica (padrão 300 s) enfileira todas as Organizations `active` da partição, para detectar *drift* feito fora do loop. Cada réplica cuida só da sua partição (`hash(resourceId) mod count`).
- **Ciclo `reconcile(resourceId)`:** com a linha bloqueada (`FOR UPDATE`), lê a organização, os metadados e o preparo para os usuários no Zitadel, decide com a função pura `decide(desired, observed)` (`create`, `update` ou `delete`; `unknown` nunca autoriza ação), executa a ação idempotente, reobserva e grava `observed`, fase, conditions, Operations e `updated`. Os campos comparados são `lifecycle`, `name`, `platformAccess`, `deletionProtection` e `userAccess`.
- **Escrita no Zitadel:** é a única identidade do tipo no provedor. Escreve a organização e o **preparo para os usuários** (decisão 0081): o Project Grant de `roles-ipm` com o catálogo `grantablePermission` do contrato, e as permissões das contas dos tipos `ipm/user` e `ipm/serviceaccount` (decisão 0094), só com o que falta e só com `platformAccess = granted`. Não cria usuários nem autoriza o dono. O ID da organização é o `resourceId`, então repetir a criação não duplica.
- **Falhas:** erro transitório do provedor devolve a Organization à fila com *backoff*; a falha da ação conta no `failure_count` e, no limite (`loop.failure_limit`, padrão 5), a `reconciliation` vira `suspended` e um `desired` suspenso vai ao outbox. Não há registro por `actionId`: repetir o ciclo é seguro porque a decisão é recalculada do estado real e as ações são idempotentes.
- **Prazos:** `loop.progress_deadline_seconds` (padrão 300) gera a condition `Progressing` `False` (`ProgressDeadlineExceeded`); uma Organization `unknown` além do prazo recebe `ObservationStale` (decisão 0090).
- Não confia em ninguém para decidir: o `desired` vigente é lido do SSOT dentro da transação, não de uma mensagem.

## 3.5 Um projeto, uma imagem, quatro papéis (decisões 0063 e 0096)

`ipm.organization` é **um projeto** (`pyproject.toml`, `uv.lock`, `Dockerfile`) e **uma imagem** (`smarkee-ipm-organization`), que contém o código dos quatro papéis. Cada papel roda como **contêiner próprio**, escolhido pelo `command` (`ipm-organization-receiver`, `-manager`, `-publisher` e `-controller`), com as suas próprias variáveis, segredos, papel de banco e identidade no NATS. Ter o código de um papel na imagem de outro não dá privilégio: ele vem da credencial.

```text
src/ipm_organization/
  common/      o que é igual em todos os papéis: settings, messaging, lifecycle, database, identity
               (token da conta de serviço), ports, resource (módulo, tipo e versão), contracts/
               (modelos gerados, base e envelope), logging_config, ids e http/health
               Os arquivos de common/ (exceto resource.py e contracts/generated.py) são gerados do
               template (templates/feature, decisão 0064): altere o modelo, não a cópia.
  receiver/  manager/  publisher/  controller/    (cada um com o seu README)
tests/
  common/  receiver/  manager/  publisher/  controller/    (unit, contract e integration)
  e2e/                                                     (projeto à parte, black-box)
migrations/    SQL do Manager e do Controller, aplicado pelo serviço ipm-organization-migrate
consumers/     manifesto do consumer do Manager
```

Um papel nunca importa outro (`tests/common/unit/test_role_isolation.py`); só o `common/`. Comandos de desenvolvimento, na raiz da feature: `uv sync`, `uv run ruff check . && uv run ruff format --check . && uv run pyright` e `uv run pytest` (a suíte e2e, em `tests/e2e`, tem projeto próprio).

## 3.6 Estrutura interna dos papéis

Cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro e sem I/O (decisão 0017): a dependência vai em um sentido só (`main → orquestração → domain`), e o `domain` nunca importa um adaptador (`tests/common/unit/test_domain_isolation.py` garante isso para todos os papéis). As pastas de cada papel:

| Papel | Pastas | README |
|---|---|---|
| Receiver | `auth/`, `domain/`, `http/`, `store/`, `transport/` (Receiver do User) | [`receiver`](src/ipm_organization/receiver/README.md) |
| Manager | `domain/`, `handlers/`, `store/`, `transport/` | [`manager`](src/ipm_organization/manager/README.md) |
| Publisher | `domain/`, `outbox/` | [`publisher`](src/ipm_organization/publisher/README.md) |
| Controller | `domain/` (`decision`, `convergence`), `drivers/` (`organization`, `metadata`, `user_access`, `identity`), `engine/` (fila, observação, ação, ciclo `reconcile`), `store/` | [`controller`](src/ipm_organization/controller/README.md) |

A saúde (`/health/*`) é de `common/http/health.py`, igual em todos os papéis.

## 3.7 Testes e2e (`tests/e2e`)

Suíte black-box (decisão 0017): fala só com o gateway, o NATS, o SSOT (limpeza) e o Docker (caos), e valida contra os schemas. Ver [`tests/e2e/README.md`](tests/e2e/README.md).

# 4. Fluxos

| Fluxo | Diagrama |
|---|---|
| Criar uma Organization, do `POST` à organização no Zitadel | [`flow/01-criar-organization`](docs/flow/01-criar-organization.svg) |
| Erros antes de entrar no loop e recusas do Manager | [`flow/02-validacao-e-borda`](docs/flow/02-validacao-e-borda.svg) |
| Atualizar (renomear) e remover | [`flow/03-atualizar-e-remover`](docs/flow/03-atualizar-e-remover.svg) |
| Falhas no Manager, na mensageria e no Publisher | [`flow/04-falhas-no-manager-e-mensageria`](docs/flow/04-falhas-no-manager-e-mensageria.svg) |
| Falhas na reconciliação e reinício do estado | [`flow/05-falhas-na-reconciliacao`](docs/flow/05-falhas-na-reconciliacao.svg) |
| Falhas na ação do provedor | [`flow/06-falhas-no-executor`](docs/flow/06-falhas-no-executor.svg) |

O fluxo de dados completo, passo a passo, está em [`docs/IPM-ORGANIZATION-DATA-FLOW.md`](docs/IPM-ORGANIZATION-DATA-FLOW.md).

> **Diagramas pendentes (decisão 0096):** os SVGs e os `.mmd` de `flow/`, `architecture/` e `database/` ainda mostram o modelo anterior, com Reconciler, Observer e Executor, os Streams `OBSERVED`, `ACTION` e `RESULT` e `organization_action_result`. O texto é o vigente.

# 5. Estados

- Fase do recurso (`phase`): [`state/01-fase-do-recurso`](docs/state/01-fase-do-recurso.svg).
- Operation (`operationStatus`): [`state/02-operation`](docs/state/02-operation.svg).

# 6. Mensageria

Este tipo só usa os Streams `REQUESTED` e `DESIRED` (decisão 0096): os Streams `OBSERVED`, `ACTION` e `RESULT` não existem para ele. O modelo geral está em [`docs/messaging/NATS.md`](../../../docs/messaging/NATS.md).

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `REQUESTED` | `receiver.requested.ipm.organization.>` | `ipm-organization-manager-requested` (durável) | Manager |
| `DESIRED` | `manager.desired.ipm.organization.>` | `ipm-organization-controller-desired-<instância>` | Controller |
| `DESIRED` | `manager.desired.ipm.permission.>` | `ipm-organization-manager-permissions-<instância>` | Manager (catálogo que atualiza o `grantPermissions`) |

O consumer de trabalho do Manager (`requested`) é durável, compartilhado e declarado pelo serviço `ipm-organization-consumer`, a partir do manifesto em `consumers/`. Os consumers do Controller e do catálogo de permission não têm manifesto: cada instância cria os próprios consumers de estado, com nome único por execução, `DeliverLastPerSubject` e `inactive_threshold`, e reconstrói o estado da mensageria (`docs/messaging/NATS.md` §7.4).

# 7. Contratos

Os contratos estão em `schemas/ipm/organization/` (e `schemas/common/`), com o índice `schemas/ipm.organization.index.json`: `desired`, `observed`, `requested-create|update|delete`, `api-create-request`, `api-update-request`, `resource` e `resource-list`. Os modelos Pydantic de cada componente são gerados (`uv run datamodel-codegen`, decisão 0012) e conferidos por teste de contrato no Manager e no Receiver. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado por `uv run python -m ipm_organization_receiver.http.openapi` e conferido por teste.

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
| Receiver | `SELECT` nas views `organization_v1` e `organization_operation_v1` | publica `requested` | só valida tokens (JWKS) |
| Manager | `SELECT`, `INSERT` e `UPDATE` em `organization`; `SELECT` e `INSERT` em `organization_operation`; `INSERT` no outbox | lê `requested` e o catálogo `DESIRED` de permission | — |
| Publisher | `SELECT` no outbox e `UPDATE (published_at)` | publica `desired` e `updated` | — |
| Controller | `SELECT`, `UPDATE` e `DELETE` em `organization`; `SELECT` e `UPDATE` em `organization_operation`; `INSERT` no outbox | lê `desired` | cria, altera, ativa, desativa e remove organizações; cria e ajusta o Grant e os papéis das contas `ipm/user` e `ipm/serviceaccount` nelas, e lê tudo isso; `IAM_ORG_MANAGER` |

Os privilégios estão em `migrations/0001-organization.sql`, `0007-organization-controller.sql` e `0008-organization-remove-action-result.sql`.

# 9. Configuração, execução e testes

Variáveis `IPM_ORGANIZATION_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros de cada papel, a ordem de precedência (linha de comando → ambiente → `config.toml` → arquivos de segredo → default) e um exemplo de execução por papel estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias: a senha do NATS (todos), as senhas dos papéis do banco (Receiver, Manager, Publisher, Controller), a audience do Receiver, o ID do projeto `roles-ipm` (Controller) e os IDs das contas dos outros tipos que o Manager concede em cada Organization (`user_access.*`). A chave da conta de serviço do Zitadel do Controller é um arquivo montado do volume `identity-bootstrap`.

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes da Organization
cd features/ipm/organization && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest   # na raiz da feature (projeto único)
# 4. Testes e2e (stack no ar): ver tests/e2e/README.md
```

Os papéis `ipm_organization_*` e o esquema `ipm` são criados por `infrastructure/dev/database/bootstrap/ipm.sql` e pelas migrações de `migrations/`. O dono do esquema é `smarkee`. Nos bancos de dev já existentes, o bootstrap só roda na criação do volume: aplique-o à mão. Os testes de integração de `manager/`, `publisher/` e `controller/` usam os papéis de login do banco de dev (`IPM_TEST_DATABASE_HOST` e `_PORT`); sem o banco, são pulados.

Depois de recriar o contêiner do Receiver, o gateway volta a resolver o nome sozinho em poucos segundos (com `502` nesse intervalo); não é preciso reiniciá-lo.

# 10. Limitações e pendências

- A Operation vira `failed` ao atingir o limite de falhas (`loop.failure_limit`) ou o prazo de progresso, e a falha aparece também na fase `Failed` da Organization (decisão 0096).
- Logo depois do `202`, a leitura pode dar `404` até o Manager gravar a Operation (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1.1).
- O Controller não cria usuários nem autoriza o dono. Os usuários da Organization são a feature `ipm/user` (decisão 0077); a Organization só os prepara (Grant e papéis, decisão 0081). Trocar a conta do Controller do User não retira os papéis da antiga (o Controller só acrescenta). Agents e os recursos derivados (OpenBao, Kubernetes) são de outras features.
- O papel de instância `IAM_ORG_MANAGER` do Controller é mais largo que o necessário, e fica assim por exceção deliberada (decisão 0060). A conta `ipm-organization-observer` (`IAM_OWNER_VIEWER`) não tem mais processo e segue no Zitadel até a limpeza declarada em `docs/platform/IMPLEMENTATION-STATUS.md`.
- As contas `ipm-user-executor/observer` e `ipm-serviceaccount-executor/observer`, que o Manager ainda recebe como configuração e concede em cada Organization, não têm mais processo: a retirada dessas concessões é lacuna declarada da decisão 0096.
- Remover não tem retenção: a organização some do Zitadel e a linha é apagada ao convergir.
- As chaves das contas de serviço vencem em 2030-01-01 e a rotação é manual (`infrastructure/dev/README.md`).
- Endurecimento comum aos módulos, ainda pendente: `cap_drop` e `no-new-privileges` no Compose, limite de taxa e de tamanho nas rotas autenticadas do gateway, e `pinned_client` no Controller (`docs/platform/IMPLEMENTATION-STATUS.md`).

# 11. Banco de dados (SSOT da Organization)

## 11.1 Entidade e relacionamento

![ER físico](docs/database/01-er-fisico.svg)

Fonte: [`01-er-fisico.mmd`](docs/database/01-er-fisico.mmd) (ainda mostra `organization_action_result`; ver a nota da seção 4).

## 11.2 Tabelas

| Tabela | Conteúdo | Quem grava |
|---|---|---|
| `ipm.organization` | Uma linha por Organization: intenção, observado, fase | Manager (intenção); Controller (observado, fase, conditions, geração confirmada; remove a linha ao convergir a remoção) |
| `ipm.organization_operation` | Uma linha por pedido aceito ou recusado | Manager insere; Controller conclui |
| `ipm.organization_outbox` | Mensagens `desired` e `updated` à espera de publicação, em ordem de `sequence` | Manager insere o `desired`; Controller insere o `updated` e o `desired` suspenso; Publisher marca `published_at` |

A tabela `ipm.organization_action_result` deixou de existir (migração `0008`, decisão 0096): a idempotência vem do ciclo atômico do Controller e das ações idempotentes do provedor.

O Receiver lê pelas views `ipm.organization_v1` (sem `failure_count`) e `ipm.organization_operation_v1` (com `requested_by`, só para autorizar a leitura).

## 11.3 O que cada coluna `jsonb` guarda

- `organization.desired`: `lifecycle`, `reconciliation`, `name`, `platformAccess`, `deletionProtection` e `ownerAccountId`.
- `organization.observed`: `name`, `platformAccess`, `organizationState`, `deletionProtection` (metadado da organização, decisão 0074) e `userAccess` (Grant e administradores, decisão 0081), lidos do Zitadel pelo Controller.
- `organization.conditions`: lista de condições do recurso.
- `organization_outbox.payload`: o envelope publicado, sem `publishedAt` e `publishedBy` (o Publisher os preenche).

## 11.4 Índices e restrições

- `organization_owner` e `organization_name` (índices de busca sobre `desired`): a cota por dono e a unicidade do nome são conferidas pelo Manager na unidade atômica, sob trava consultiva, e não por restrição única.
- `organization_operation`: `(operation_status = 'rejected') = (operation_status_reason IS NOT NULL)` e `= (desired_generation IS NULL)`.
- `organization_outbox_pending` (parcial, `published_at IS NULL`) e `organization_outbox_published`; `message_id` único.
- Limites de tamanho e padrões nos identificadores, nas fases e nos estados (`CHECK`), e `jsonb` limitado a 256 KiB.

## 11.5 Quem grava o quê

Ver o mapa em [`docs/IPM-ORGANIZATION-DATA-FLOW.md`](docs/IPM-ORGANIZATION-DATA-FLOW.md) §9 e os privilégios em `migrations/0001-organization.sql`, `0007-organization-controller.sql` e `0008-organization-remove-action-result.sql`.

## 11.6 Dados pessoais no banco

Nenhum dado pessoal: só o ID do dono no Zitadel (`ownerAccountId`, dentro de `desired`) e o nome da Organization.

## 11.7 Consultas úteis (dev)

```sql
-- Organizations por fase e situação
SELECT phase, lifecycle, count(*) FROM ipm.organization GROUP BY 1, 2 ORDER BY 1, 2;

-- Organizations por dono
SELECT desired ->> 'ownerAccountId' AS dono, count(*) FROM ipm.organization GROUP BY 1;

-- Atraso do outbox (idade da mensagem pendente mais antiga)
SELECT now() - min(created_at) AS atraso FROM ipm.organization_outbox WHERE published_at IS NULL;

-- Operations de um recurso
SELECT operation_id, operation_type, operation_status, operation_status_reason, desired_generation
  FROM ipm.organization_operation WHERE resource_id = '<resourceId>' ORDER BY created_at;
```
