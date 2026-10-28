# sum.service

Módulo `sum`, tipo `service`: o uso de um serviço da plataforma (hoje, `ipm`) por um usuário. Um usuário
liga ou desliga um serviço, e a ligação concede ou revoga as permissões desse serviço no Zitadel (decisão 0033).
É o SUM (Service Usage Manager). A estrutura segue a de `features/core/account`.

Decisões que definem esta feature: `0033` (o SUM), `0098` (API síncrona e fim da Operation), `0100` (sem chamadas HTTP entre features: projeções locais do `DESIRED`), `0096` (o loop unificado no Controller), `0079` (catálogo e rollout), `0044` (conta removida), `0040` (desligar `ipm` com Organizations) e `0032` (permissões por projeto).

# 1. Estado da implementação

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`sum-service-api`) | API `/v1/sum/services`: autentica, confere a permissão `sum.<serviço>.<ação>` e admite a escrita síncrona numa transação (recurso e `desired` no outbox). Contrato em `openapi.json` |
| Publisher | `publisher/` (`sum-service-publisher`) | Publica o outbox no NATS (template, decisão 0065) |
| Controller | `controller/` (`sum-service-controller`) | Lê o `desired` do Stream `DESIRED` e, por ligação, observa o Zitadel, decide, age e reobserva numa só transação; grava o estado e o `updated` no outbox. Faz o rollout do catálogo na partida e apaga as ligações de uma conta removida |
| Telemeter (observabilidade, **não é papel do loop**) | `telemeter/` (`sum-service-telemeter`) | Recebe os logs e os spans de app da feature (do `telemetry-router`) |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo e resiliência (`E2E_CHAOS=1`); **não são um componente** |
| CLI | `clients/cli` | `sk sum service enable|disable|get|list` |

Além dos papéis, o serviço `sum-service-migrate` (migrações) roda e sai.

**Não verificado de ponta a ponta:** a suíte `tests/e2e` foi reescrita para a API síncrona e ainda não foi executada contra a stack real (`docs/platform/IMPLEMENTATION-STATUS.md`).

# 2. Arquitetura

Os papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios, com o próprio papel de banco (`sum_service_<papel>`, em `infrastructure/dev/database/bootstrap/sum.sql`), a própria identidade no NATS e, quando usa o Zitadel, a própria conta de serviço. O fluxo de dados completo está em [`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md). Os diagramas do modelo anterior (Receiver, Manager, Reconciler, Observer, Executor e Operation) foram removidos.

```text
CLI -> gateway -> sum-service-api -> SSOT (recurso + outbox) -> sum-service-publisher -> DESIRED
DESIRED -> sum-service-controller -> Zitadel (permissões) -> SSOT (observado, fase) -> outbox -> UPDATED
```

# 3. Papéis e componentes

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| API | `sum-service-api` | `sum_service_api` (`SELECT`, `INSERT` e `UPDATE` em `service`; `SELECT` na view; `INSERT` no outbox; `SELECT` e `INSERT` na idempotência; sem `DELETE`) | — | SSOT (`sum.service*`) e outbox |
| Publisher | `sum-service-publisher` | `sum_service_publisher` | — | `published_at` do outbox; NATS |
| Controller | `sum-service-controller` | `sum_service_controller` (`SELECT`, `UPDATE` e `DELETE` em `service`; `INSERT` só no outbox) | `sum-service-controller` (`ORG_OWNER_VIEWER` na `register`; `PROJECT_GRANT_OWNER` no Grant de `roles-ipm`) | as permissões no Zitadel; SSOT (observado, fase) |

## 3.1 API (`sum-service-api`)

- Rotas sob `/v1/sum/services`: `POST` liga (`201` + `Resource`), `GET` lista, `GET /{resourceId}` lê e `DELETE /{resourceId}?resourceVersion=` desliga (`202` + `Resource`). Não há Operation: a convergência se lê no próprio recurso (`observedGeneration` igual a `desiredGeneration` com `phase` `Ready`).
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-sum`, `exp`). O dono da ligação é o `sub`: nunca vem do corpo, que só tem `service`. Cada ação exige a permissão `sum.<serviço>.<enable|disable|get>`.
- Uma ligação de outro dono responde `404`, para não revelar que existe. `Idempotency-Key` (1 a 128 caracteres) torna o `POST` e o `DELETE` repetíveis: a repetição devolve o mesmo recurso, e outro pedido com a mesma chave é `422 IdempotencyKeyReused`.
- **Admissão (decisão 0098):** numa transação, trava o par dono + serviço (`lock_pair`), confere o catálogo (`409 ServiceNotAvailable`), o par já ligado (`409 AlreadyEnabled`), a versão (`409 Conflict`) e as pré-condições, e grava o recurso e o `desired` no outbox. Ligar de novo um par desligado reaproveita o recurso, com uma geração nova.
- **Pré-condições por projeção local do `DESIRED` (decisão 0100):** ligar exige uma Billing Account do dono (`409 BillingAccountRequired`; divergência declarada da decisão 0082, que pedia a conta `Ready`), e desligar `ipm` exige que o dono não tenha Organizations (`409 ResourcesAttached`, decisão 0040). Antes da primeira sincronização das projeções, `503 ProjectionSyncPending` com `Retry-After`. A API não chama outras APIs.
- Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado. Não expõe `/docs` nem `/openapi.json`: o contrato descritivo é o arquivo versionado `openapi.json`, conferido por teste.

## 3.2 Publisher e Controller

- **Publisher:** o do template (decisão 0065), sem regra do tipo. Publica o `desired` (que a API gravou) e o `updated` (que o Controller gravou) do mesmo outbox, em `manager.<tipo>.sum.service.<resourceId>.changed`, com `Nats-Msg-Id` igual ao `messageId`. Uma instância ativa por trava consultiva de sessão; recusa permanente mantém a mensagem pendente e tira o Publisher de `ready`, sem derrubar o processo (decisão 0018).
- **Controller:** consome o Stream `DESIRED` e, para cada ligação, executa o ciclo atômico `reconcile`. Detalhes no [README do Controller](src/sum_service/controller/README.md).
  - **Decisão:** as `servicePermissions` precisam estar com o usuário, e as outras permissões gerenciadas (`managedPermissions`, por exemplo uma que saiu do catálogo) não podem estar. `disable` tira só as gerenciadas e mantém as demais.
  - **Observação:** lê o usuário dono (`404` é `absent`; outra falha é `unknown`, que nunca autoriza ação) e as autorizações nos projetos de permissões.
  - **Rollout do catálogo (decisão 0079):** na partida, cada ligação cujo `desired` difere do que o catálogo atual produz ganha uma geração nova (`requested_by = system:catalog`).
  - **Conta removida (decisão 0044):** consome o `updated` de `core.account` com `removed` e apaga as ligações do dono; repetir não tem efeito.
- A linha de uma ligação desfeita **não é apagada** na convergência (decisão 0033): só a remoção da conta a apaga.

## 3.3 Um projeto, uma imagem, três contêineres (decisão 0063)

```text
src/sum_service/
  common/      o que é igual em todos os papéis: settings, messaging, lifecycle, database, identity,
               ports, resource (módulo, tipo e versão), contracts/ (modelos gerados, base e envelope),
               logging_config, ids e http/health. Os arquivos de common/ (exceto resource.py,
               service_rules.py e contracts/generated.py) são gerados do template (decisão 0064):
               altere o modelo, não a cópia.
  api/  publisher/  controller/    (cada um com o seu README)
tests/
  common/  api/  publisher/  controller/    (unit, contract e integration)
  e2e/                                       (projeto à parte, black-box)
migrations/    SQL do tipo, aplicado pelo serviço sum-service-migrate
```

Um papel nunca importa outro (`tests/common/unit/test_role_isolation.py`); só o `common/`. Comandos de desenvolvimento, na raiz da feature: `uv sync`, `uv run ruff check . && uv run ruff format --check . && uv run pyright` e `uv run pytest` (a suíte e2e, em `tests/e2e`, tem projeto próprio).

A saúde (`/health/*`) é de `common/http/health.py`. A API só fica `ready` depois da sincronização das projeções.

# 4. Fluxos

O fluxo de dados completo, passo a passo, está em [`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md).

# 5. Estados

`phase`: `Pending` (ao gravar ou ao desligar), `Reconciling`, `Ready`, `Failed` (não terminal) e `Deleting`. `Ready` só vem de uma observação posterior à geração (decisão 0072).

# 6. Mensageria

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `DESIRED` | `desired.sum.service.>` | `sum-service-controller-desired-<instância>` | Controller |
| `DESIRED` | `desired.ipm.organization.>` e `desired.bsm.account.>` | `sum-service-api-<módulo>-<tipo>-<instância>` | API (projeções das pré-condições) |
| `UPDATED` | `updated.core.account.>` | `sum-service-controller-account-removed-<instância>` | Controller (conta removida) |
| `DESIRED`, `UPDATED` | `manager.{desired,updated}.sum.service.>` | (publicados) | Publisher publica; consumidores externos leem |

Os consumers são de estado: cada instância cria os próprios, com nome único por execução, `DeliverLastPerSubject` e `inactive_threshold`, e reconstrói o estado da mensageria (`docs/messaging/NATS.md`). Não há Stream `REQUESTED`, `OBSERVED`, `ACTION` nem `RESULT` para o tipo (decisões 0096 e 0098).

# 7. Contratos

Os contratos estão em `schemas/sum/service/` (e `schemas/common/`), com o índice `schemas/sum.service.index.json`: `desired`, `observed`, `api-create-request`, `api-list-response` e `resource`. Os modelos Pydantic são gerados (`uv run datamodel-codegen`, decisão 0012) e conferidos por teste de contrato. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado por `uv run python -m sum_service.api.http.openapi` e conferido por teste.

# 8. Segurança e privacidade

- **Dono pelo token:** o `ownerAccountId` é o `sub` do token. O corpo do `POST` só aceita `service`; qualquer outro campo é recusado pelo contrato.
- **Sem dados pessoais no SSOT:** só o ID do usuário no Zitadel (`owner_account_id`) e o nome do serviço. Não há e-mail, nome nem token.
- **Isolamento das permissões:** só o Controller concede, e o Zitadel nega o que estiver fora do Grant de `roles-ipm` (decisão 0032). O catálogo (serviço → permissões) é configuração da API e do Controller (`SUM_SERVICE_{API,CONTROLLER}_CATALOG_PERMISSIONS`, obrigatório); a API copia para o `desired` as permissões que o usuário deve ter (`servicePermissions`) e as que a ligação controla (`managedPermissions`).
- **Erros e logs:** nenhuma resposta ou log repete o valor enviado, senhas ou tokens; as configurações escondem os segredos (`SecretStr`).

## 8.1 Identidades e privilégios por papel

| Papel | Banco | NATS | Zitadel |
|---|---|---|---|
| API | `SELECT` na view `service_v1`; `SELECT`, `INSERT` e `UPDATE` em `service`; `INSERT` no outbox; `SELECT` e `INSERT` em `service_idempotency` | lê `DESIRED` (projeções) | só valida tokens (JWKS) |
| Publisher | `SELECT` no outbox e `UPDATE (published_at)` | publica `desired` e `updated` | — |
| Controller | `SELECT`, `UPDATE` e `DELETE` em `service`; `INSERT` no outbox | lê `DESIRED` e o `UPDATED` de `core.account` | `ORG_OWNER_VIEWER` na `register`; `PROJECT_GRANT_OWNER` no Grant de `roles-ipm` |

# 9. Configuração, execução e testes

Variáveis `SUM_SERVICE_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros de cada papel, a ordem de precedência (linha de comando → ambiente → `config.toml` → arquivos de segredo → default) e um exemplo de execução por papel estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias.

**Trocar o catálogo:** edite `SUM_SERVICE_API_CATALOG_PERMISSIONS` e `SUM_SERVICE_CONTROLLER_CATALOG_PERMISSIONS` (iguais) no `.env` e rode `docker compose up -d` na pasta da feature. Na partida, o Controller faz o rollout: cada ligação cujo `desired` difere do catálogo novo ganha uma geração nova, e o loop concede a permissão nova ou revoga a que saiu, inclusive de quem ligou antes. As permissões novas precisam existir antes no `roles-ipm` e no Grant dele para a `register` (`infrastructure/dev/README.md`).

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes do SUM
cd features/sum/service && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest   # na raiz da feature (projeto único)
# 4. Testes e2e (stack no ar): ver tests/e2e/README.md
```

Os papéis `sum_service_*` e o esquema `sum` são criados por `infrastructure/dev/database/bootstrap/sum.sql` e pelas migrações de `migrations/`. Nos bancos de dev já existentes, o bootstrap só roda na criação do volume: aplique-o à mão como `postgres`. Os testes de integração pedem o PostgreSQL de dev com os papéis `sum_service_*_login`; sem ele, são pulados.

Depois de recriar o contêiner da API, reinicie o gateway (cache de DNS).

# 10. Limitações e pendências

- A verificação de e-mail do solicitante (a Account exige) ainda não foi decidida para o SUM.
- Desligar não apaga: a linha fica como histórico até a conta ser removida (decisão 0033), e ainda não há retenção das linhas desligadas.
- Kill switch e a visão de operador (`sum.service.admin`) não existem.
- A validade curta do access token (decisão 0033, opção B) não está aplicada no Zitadel de dev; a CLI já renova a sessão.
- As chaves das contas de serviço vencem em 2027-10-15 e a rotação é manual (`infrastructure/dev/README.md`).
- Em stg/prd é preciso repetir a migração `0009-service-api`, os papéis e logins, a conta Zitadel `sum-service-controller`, a rota do gateway e a remoção dos consumers antigos (`docs/platform/IMPLEMENTATION-STATUS.md`). As contas `sum-service-executor` e `sum-service-observer` ficam sem uso.
- Endurecimento comum aos módulos, ainda pendente: `cap_drop` e `no-new-privileges` no Compose e limite de taxa e de tamanho nas rotas autenticadas do gateway (`docs/platform/IMPLEMENTATION-STATUS.md`).

# 11. Banco de dados (SSOT do SUM)

## 11.1 Tabelas

| Tabela | Conteúdo | Quem grava |
|---|---|---|
| `sum.service` | Uma linha por par dono + serviço (ligada ou desligada; religar reaproveita a linha): intenção, observado, fase | API (admissão); Controller (observação e remoção da conta) |
| `sum.service_outbox` | Mensagens `desired` e `updated` à espera de publicação, em ordem de `sequence` | API e Controller inserem; Publisher marca `published_at` |
| `sum.service_idempotency` | Chave de idempotência do cliente, por solicitante | API |

A API lê pela view `sum.service_v1` (sem `failure_count`). A Operation (`service_operation`) e o `service_action_result` deixaram de existir (migração `0009-service-api`).

## 11.2 O que cada coluna `jsonb` guarda

- `service.desired`: `lifecycle`, `reconciliation`, `ownerAccountId`, `service`, `servicePermissions` (as do catálogo; vazias ao desligar) e `managedPermissions` (as que a ligação controla: as do catálogo mais as que saíram dele, para serem revogadas; decisão 0079).
- `service.observed`: `servicePermissions` lidas do Zitadel.
- `service.conditions`: lista de condições do recurso.
- `service_outbox.payload`: o envelope, sem `publishedAt` e `publishedBy` (o Publisher os preenche).

## 11.3 Índices e restrições

- `service_active_link` (único parcial, `WHERE lifecycle = 'present'`): no máximo uma ligação ativa por dono e serviço, mesmo com pedidos concorrentes.
- `lifecycle = 'absent'` exige `servicePermissions` vazio (restrição de tabela).
- `service_outbox_pending` (parcial, `published_at IS NULL`) e `service_outbox_published`; `message_id` único.
- Limites de tamanho e padrões nos identificadores, nas fases e nos estados (`CHECK`), e `jsonb` limitado a 256 KiB.

## 11.4 Quem grava o quê

Ver o mapa em [`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md) §6 e os privilégios em `migrations/0001-service.sql` e `migrations/0009-service-api.sql`.

## 11.5 Dados pessoais no banco

Nenhum dado pessoal: só o ID do usuário no Zitadel (`owner_account_id`) e o nome do serviço.

## 11.6 Consultas úteis (dev)

```sql
-- Ligações por fase e situação
SELECT phase, lifecycle, count(*) FROM sum.service GROUP BY 1, 2 ORDER BY 1, 2;

-- Atraso do outbox (idade da mensagem pendente mais antiga)
SELECT now() - min(created_at) AS atraso FROM sum.service_outbox WHERE published_at IS NULL;
```
