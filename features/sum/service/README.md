# sum.service

Módulo `sum`, tipo `service`: o uso de um serviço da plataforma (hoje, `ipm`) por um usuário. Um usuário
liga ou desliga um serviço, e a ligação concede ou revoga as roles desse serviço no Zitadel (decisão 0033).
É o SUM (Service Usage Manager). A estrutura segue a de `features/core/account`.

# 1. Estado da implementação

Os seis componentes do loop e a CLI estão implementados e rodam no dev (Compose). A suíte e2e liga e desliga
`ipm` pela API, com falha de componente, e todas as respostas são validadas contra os schemas.

| Papel | Diretório | Estado |
|---|---|---|
| Receiver | `receiver/` | API `/v1/sum/services`: autentica, confere a role, publica `requested`. Contrato em `openapi.json` |
| Manager | `manager/` | Consome `requested`, grava a ligação, a Operation e o outbox; aplica `observed` e resultados |
| Publisher | `publisher/` | Publica o outbox no NATS, com trava de sessão, envelope estrito e `Nats-Msg-Id` |
| Reconciler | `reconciler/` | Decisão e motor; estado reconstruído da mensageria a cada início |
| Observer | `observer/` | Lê o Zitadel só de leitura e publica `observed`; partição por `resourceId` |
| Executor | `executor/` | Concede e revoga as roles no Zitadel; revalida cada ação; um laço por partição |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo e caos (Manager, Executor, Publisher, Reconciler e Observer) |

A CLI é o comando `sk sum service enable|disable|get|list` (`clients/cli`). Desabilitar o `ipm` é recusado (`409 ResourcesAttached`) enquanto o dono tiver Organizations: o Receiver pergunta ao Receiver do `ipm`, com o token do solicitante (decisão 0040).

# 2. Arquitetura

![Componentes](docs/architecture/01-componentes.svg)

Fonte: [`01-componentes.mmd`](docs/architecture/01-componentes.mmd). O fluxo de dados completo está em
[`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md).

# 3. Papéis e componentes

Os seis papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner
próprios: cada papel tem o próprio papel de banco (`sum_service_<papel>`, em
`infrastructure/dev/database/bootstrap/sum.sql`), a própria identidade no NATS e, quando usa o Zitadel, a
própria conta de serviço. O código igual em todos fica em `common/`, e nenhum papel importa outro.

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| Receiver | `sum-service-receiver` | `sum_service_receiver` (só leitura das views) | — | `requested` no NATS |
| Manager | `sum-service-manager` | `sum_service_manager` | — | SSOT (`sum.service*`) e outbox |
| Publisher | `sum-service-publisher` | `sum_service_publisher` | — | `published_at` do outbox; NATS |
| Reconciler | `sum-service-reconciler` | — | — | `action` no NATS |
| Observer | `sum-service-observer` | — | `sum-service-observer` (`ORG_OWNER_VIEWER` na `register`, leitura) | `observed` no NATS |
| Executor | `sum-service-executor` | — | `sum-service-executor` (`PROJECT_GRANT_OWNER` só no Grant de `roles-ipm`) | `completed` e `failed`; as roles no Zitadel |

## 3.1 Receiver (`sum-service-receiver`)

- Rotas sob `/v1/sum/services` (decisão 0030): `POST` liga, `GET` lista, `GET /{resourceId}` lê, `DELETE
  /{resourceId}?resourceVersion=` desliga, `GET /{resourceId}/operations/{operationId}` acompanha a Operation.
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-sum`, `exp`). O dono da ligação é o `sub`: nunca
  vem do corpo, que só tem `service`. Cada ação exige a role `sum.<serviço>.<enable|disable|get>`.
- Uma ligação de outro dono responde `404`, para não revelar que existe. `Idempotency-Key` (1 a 128 caracteres) torna o
  `POST` e o `DELETE` repetíveis: a repetição devolve o mesmo aceite, e outro pedido com a mesma chave é `422`.
- Só lê o SSOT, pelas views `sum.service_v1` e `sum.service_operation_v1`. Não expõe `/docs` nem `/openapi.json`: o
  contrato descritivo é o arquivo versionado `openapi.json`, conferido por teste.
- Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado.

## 3.2 Manager (`sum-service-manager`)

- Único escritor do SSOT (`sum.service`, `sum.service_operation`, `sum.service_action_result`) e do outbox.
- Consome `requested` (criar e desligar), `observed` e os resultados `completed` e `failed`. Decide pelo catálogo
  (serviço → roles, `SUM_SERVICE_MANAGER_CATALOG_ROLES`) e pelo índice único parcial `service_active_link`.
- Aceita ou recusa com motivo (`service_unavailable`, `already_exists`, `not_found`, `conflict`). Só insere no outbox:
  a publicação é do Publisher. ACK depois do `COMMIT`; falha transitória do banco é `RETRY`; mensagem fora do contrato
  (inclusive de outra versão `MAJOR`) é `TERM`.
- Aplica `observed` e os resultados pelos handlers do template (decisão 0080): geração confirmada, `updated`, limite de
  falhas com suspensão e condition `Progressing` com prazo. Acompanha as Operations (`in_progress`, `completed`).
- Consome o `updated` de `core.account` com `removed` e apaga as ligações do dono (decisão 0044): idempotente, e o histórico de Operations fica.

## 3.3 Publisher (`sum-service-publisher`)

- Lê o outbox em ordem de `sequence`, valida o envelope de forma estrita, acrescenta `publishedAt` e `publishedBy` e
  publica em `manager.desired.sum.service.<resourceId>.changed`, com `Nats-Msg-Id` igual ao `messageId`. Marca
  `published_at` depois da confirmação.
- Uma instância ativa por trava consultiva de sessão. Recusa permanente (ou envelope inválido) mantém a mensagem
  pendente, registra `ERROR` e tira o Publisher de `ready`, sem derrubar o processo (decisão 0018).

## 3.4 Reconciler (`sum-service-reconciler`)

- Mantém em memória o último `desired`, `observed` e resultado de cada ligação, reconstruídos a cada início (consumer
  por instância, `DeliverLastPerSubject`). Não acessa o SSOT.
- Decide com as guardas do loop (sem os dois estados, suspenso, `observed` `unknown` ou vencido, ação pendente, backoff)
  e publica a `action` `update` com `Nats-Msg-Id` igual ao `actionId`. Reavalia periodicamente, com jitter.

## 3.5 Observer (`sum-service-observer`)

- Lê o Zitadel só de leitura e publica `observed` (`present` com as roles do serviço, `absent` só quando o Zitadel confirma
  que o usuário não existe, `unknown` para qualquer falha de leitura). Observa quando o `desired` muda, depois de cada
  resultado e periodicamente (com jitter). Com várias réplicas, cada uma observa só a sua partição.

## 3.6 Executor (`sum-service-executor`)

- Único componente que concede e revoga roles de serviço no Zitadel, por `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm`.
- Valida a mensagem (emissor `reconciler`, tipo, módulo, versão `MAJOR`), não repete um `actionId` já concluído e
  revalida a ação contra o `desired` vigente (geração, `suspended`, `lifecycle`). Ação velha ou recusada vira `failed`
  permanente; erro transitório volta à fila. Um consumer e um laço por partição do `ACTION`.

## 3.6.1 Um projeto, uma imagem, seis contêineres (decisão 0063)

`sum.service` é **um projeto** (`pyproject.toml`, `uv.lock`, `Dockerfile`) e **uma imagem** (`smarkee-sum-service`), que contém o código dos seis papéis. Cada papel roda como **contêiner próprio**, escolhido pelo `command` (`sum-service-receiver`, `-manager`, `-publisher`, `-observer`, `-reconciler` e `-executor`), com as suas próprias variáveis, segredos, papel de banco e identidade no NATS. Ter o código de um papel na imagem de outro não dá privilégio: ele vem da credencial.

```text
src/sum_service/
  common/      o que é igual em todos os papéis: settings, messaging, lifecycle, database, identity
               (token da conta de serviço), ports, resource (módulo, tipo e versão), contracts/
               (modelos gerados, base e envelope), logging_config, ids e http/health
               Os arquivos de common/ (exceto resource.py e contracts/generated.py) são gerados do
               template (templates/feature, decisão 0064): altere o modelo, não a cópia.
  receiver/  manager/  publisher/  observer/  reconciler/  executor/    (cada um com o seu README)
tests/
  common/  receiver/  manager/  publisher/  observer/  reconciler/  executor/    (unit, contract e integration)
  e2e/                                                                             (projeto à parte, black-box)
migrations/    SQL do Manager, aplicado pelo serviço sum-service-migrate
consumers/     manifestos dos consumers do Manager e do Executor
```

Um papel nunca importa outro (`tests/common/unit/test_role_isolation.py`); só o `common/`. Comandos de desenvolvimento, na raiz da feature: `uv sync`, `uv run ruff check . && uv run ruff format --check . && uv run pyright` e `uv run pytest` (a suíte e2e, em `tests/e2e`, tem projeto próprio).

## 3.7 Estrutura interna dos papéis

Cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro e sem I/O (decisão 0017): a dependência vai em um sentido só (`main → orquestração → domain`), e o `domain` nunca importa um adaptador (`tests/common/unit/test_domain_isolation.py` garante isso para todos os papéis). As pastas de cada papel:

| Papel | Pastas | README |
|---|---|---|
| Receiver | `auth/`, `domain/`, `http/`, `store/`, `transport/` | [`receiver`](src/sum_service/receiver/README.md) |
| Manager | `domain/`, `handlers/`, `store/`, `transport/` | [`manager`](src/sum_service/manager/README.md) |
| Publisher | `domain/`, `outbox/` | [`publisher`](src/sum_service/publisher/README.md) |
| Reconciler | `domain/`, `engine/`, `transport/` | [`reconciler`](src/sum_service/reconciler/README.md) |
| Observer | `domain/`, `drivers/` (leitura: `user`, `authorization`), `engine/`, `provider/` (conexão só de leitura), `transport/` | [`observer`](src/sum_service/observer/README.md) |
| Executor | `actions/`, `domain/`, `drivers/` (escrita: `authorization`), `engine/`, `provider/` (conexão de escrita), `transport/` | [`executor`](src/sum_service/executor/README.md) |

A saúde (`/health/*`) é de `common/http/health.py`, igual em todos os papéis.

## 3.8 Testes e2e (`tests/e2e`)

Suíte black-box (decisão 0017): fala só com o gateway, o SSOT (limpeza) e o Docker (caos), e valida contra os schemas. Ver
[`tests/e2e/README.md`](tests/e2e/README.md).

# 4. Fluxos

| Fluxo | Diagrama |
|---|---|
| Ligar um serviço, do `POST` às roles no Zitadel | [`flow/01-ligar-servico`](docs/flow/01-ligar-servico.svg) |
| Erros antes de entrar no loop e recusas do Manager | [`flow/02-validacao-e-borda`](docs/flow/02-validacao-e-borda.svg) |
| Desligar um serviço | [`flow/03-desligar-servico`](docs/flow/03-desligar-servico.svg) |
| Falhas no Manager, na mensageria e no Publisher | [`flow/04-falhas-no-manager-e-mensageria`](docs/flow/04-falhas-no-manager-e-mensageria.svg) |
| Falhas na reconciliação e reinício do estado | [`flow/05-falhas-na-reconciliacao`](docs/flow/05-falhas-na-reconciliacao.svg) |
| Falhas no Executor | [`flow/06-falhas-no-executor`](docs/flow/06-falhas-no-executor.svg) |

O fluxo de dados completo, passo a passo, está em [`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md).

# 5. Estados

- Fase do recurso (`phase`): [`state/01-fase-do-recurso`](docs/state/01-fase-do-recurso.svg).
- Operation (`operationStatus`): [`state/02-operation`](docs/state/02-operation.svg).

# 6. Mensageria

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `REQUESTED` | `receiver.requested.sum.service.>` | `sum-service-manager-requested` (durável) | Manager |
| `DESIRED` | `manager.desired.sum.service.>` | `sum-service-{reconciler,observer}-desired-<instância>` | Reconciler, Observer |
| `OBSERVED` | `observer.observed.sum.service.>` | `sum-service-manager-observed` (durável); `sum-service-reconciler-observed-<instância>` | Manager, Reconciler |
| `RESULT` | `executor.completed.sum.service.>`, `executor.failed.sum.service.>` | `sum-service-manager-{completed,failed}` (duráveis); `sum-service-{reconciler,observer}-result-<instância>` | Manager, Reconciler, Observer |
| `ACTION` | `reconciler.action.sum.service.<partição>.>` | `sum-service-executor-action-p0..p3` (duráveis) | Executor |

Os consumers de trabalho (Manager e Executor) são duráveis, compartilhados e declarados pelo serviço
`sum-service-consumer`, a partir dos manifestos em `consumers/`. O Reconciler e o
Observer não têm manifesto: cada instância cria os próprios consumers de estado, com nome único por execução,
`DeliverLastPerSubject` e `inactive_threshold`, e reconstrói o estado da mensageria (`docs/NATS.md` §7.4).

No `ACTION`, a partição é aplicada pelo servidor (`subject_transform`, decisão 0018), com `max_ack_pending = 1`: uma
ação por recurso por vez. O Executor roda um laço por partição, no mesmo processo.

# 7. Contratos

Os contratos estão em `schemas/sum/service/` (e `schemas/common/`), com o índice `schemas/sum.service.index.json`:
`desired`, `observed`, `requested-create`, `requested-delete`, `api-create-request`, `api-list-response` e `resource`.
Os modelos Pydantic de cada componente são gerados (`uv run datamodel-codegen`, decisão 0012) e conferidos por teste de
contrato no Manager e no Receiver. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado
por `uv run python -m sum_service.receiver.http.openapi` e conferido por teste.

# 8. Segurança e privacidade

- **Dono pelo token:** o `ownerAccountId` é o `sub` do token. O corpo do `POST` só aceita `service`; qualquer outro campo é
  recusado pelo contrato.
- **Sem dados pessoais no SSOT:** só o ID do usuário no Zitadel (`owner_account_id`) e o nome do serviço. Não há e-mail,
  nome nem token.
- **Isolamento das roles:** só o Executor concede, e o Zitadel nega o que estiver fora do Grant de `roles-ipm`
  (decisão 0032). O catálogo (serviço → roles) existe **só no Manager** (decisão 0079): ele copia para o `desired` as roles
  que o usuário deve ter (`serviceRoles`) e as que a ligação controla (`managedRoles`), e o Observer e o Executor leem só
  o `desired`.
- **Última barreira:** o Executor não confia em quem enviou a ação: confere o emissor, a versão e o `desired` vigente, e
  não assume `present` quando falta o `lifecycle`.
- **Erros e logs:** nenhuma resposta ou log repete o valor enviado, senhas ou tokens; as configurações escondem os
  segredos (`SecretStr`).

## 8.1 Identidades e privilégios por papel

| Papel | Banco | NATS | Zitadel |
|---|---|---|---|
| Receiver | `SELECT` nas views `service_v1` e `service_operation_v1` | publica `requested` | só valida tokens (JWKS) |
| Manager | `SELECT`, `INSERT`, `UPDATE` e `DELETE` em `service`; `SELECT`, `INSERT` e `UPDATE` em `service_operation`; `SELECT` e `INSERT` em `service_action_result`; `INSERT` no outbox | lê `requested`, `observed`, resultados | — |
| Publisher | `SELECT` no outbox e `UPDATE (published_at)` | publica `desired` | — |
| Reconciler | — | lê o estado; publica `action` | — |
| Observer | — | lê `desired` e resultados; publica `observed` | leitura, `ORG_OWNER_VIEWER` na `register` |
| Executor | — | lê `action`; publica `completed` e `failed` | `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm` |

# 9. Configuração, execução e testes

Variáveis `SUM_SERVICE_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros de cada papel, a ordem de precedência (linha de comando → ambiente → `config.toml` → arquivos de segredo → default) e um exemplo de execução por papel estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias:
a senha do NATS (todos), as senhas dos papéis do banco (Receiver, Manager, Publisher), a audience do Receiver, o catálogo
(só do Manager, decisão 0079) e os IDs no Zitadel (Observer e Executor).

**Trocar o catálogo:** edite `SUM_SERVICE_MANAGER_CATALOG_ROLES` no `.env` e rode `docker compose up -d` na pasta da feature
(sem nome de serviço: o Compose recria só o que mudou). Na partida, o Manager faz o rollout: cada ligação cujo `desired`
difere do catálogo novo ganha uma geração nova, com uma Operation `update` de `system:catalog`, e o loop concede a role
nova ou revoga a que saiu, inclusive de quem ligou antes. As roles novas precisam existir antes no `roles-ipm` e no Grant
dele para a `register` (`infrastructure/dev/README.md`).

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes do SUM
cd features/sum/service && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest   # na raiz da feature (projeto único)
# 4. Testes e2e (stack no ar): ver tests/e2e/README.md
```

O papel `sum_service_*` e o esquema `sum` são criados por `infrastructure/dev/database/bootstrap/sum.sql` e pelas migrações
de `migrations/`. O dono do esquema é `smarkee`. Nos bancos de dev já existentes, o bootstrap só roda na criação do
volume: aplique-o à mão. Os testes de integração de `manager/` e `publisher/` pedem as URLs dos papéis e as credenciais do
messaging de dev (ver o README de cada componente); sem elas, são pulados.

Depois de recriar o contêiner do Receiver, o gateway volta a resolver o nome sozinho em poucos segundos (com `502` nesse
intervalo); não é preciso reiniciá-lo.

# 10. Limitações e pendências

- A Operation não vira `failed`: a falha aparece na fase `Failed` da ligação.
- Logo depois do `202`, a leitura pode dar `404` até o Manager gravar a Operation (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.1).
- A verificação de e-mail do solicitante (a Account exige) ainda não foi decidida para o SUM.
- Desligar não apaga: a linha fica como histórico. A estratégia de apagar os recursos do usuário no serviço fica para depois
  (decisão 0033), e ainda não há retenção das linhas desligadas.
- Kill switch e a visão de operador (`sum.service.admin`) não existem.
- A validade curta do access token (decisão 0033, opção B) não está aplicada no Zitadel de dev; a CLI já renova a sessão.
- As chaves das contas de serviço vencem em 2027-10-15 e a rotação é manual (`infrastructure/dev/README.md`).
- Endurecimento comum aos módulos, ainda pendente: `cap_drop` e `no-new-privileges` no Compose, limite de taxa e de tamanho
  nas rotas autenticadas do gateway, e `pinned_client` no Executor (`docs/IMPLEMENTATION-STATUS.md`).

# 11. Banco de dados (SSOT do SUM)

## 11.1 Entidade e relacionamento

![ER físico](docs/database/01-er-fisico.svg)

Fonte: [`01-er-fisico.mmd`](docs/database/01-er-fisico.mmd).

## 11.2 Tabelas

| Tabela | Conteúdo | Quem grava |
|---|---|---|
| `sum.service` | Uma linha por par dono + serviço (ligada ou desligada; religar reaproveita a linha): intenção, observado, fase | Manager |
| `sum.service_operation` | Uma linha por pedido aceito ou recusado | Manager |
| `sum.service_outbox` | Mensagens `desired` à espera de publicação, em ordem de `sequence` | Manager insere; Publisher marca `published_at` |
| `sum.service_action_result` | Resultado já contado, por `actionId` | Manager |

O Receiver lê pelas views `sum.service_v1` (sem `failure_count`) e `sum.service_operation_v1` (com `requested_by`, só para
autorizar a leitura).

## 11.3 O que cada coluna `jsonb` guarda

- `service.desired`: `lifecycle`, `reconciliation`, `ownerAccountId`, `service`, `serviceRoles` (as do catálogo; vazias ao
  desligar) e `managedRoles` (as que a ligação controla: as do catálogo mais as que saíram dele, para serem revogadas;
  decisão 0079).
- `service.observed`: `serviceRoles` lidas do Zitadel.
- `service.conditions`: lista de condições do recurso.
- `service_outbox.payload`: o envelope `desired`, sem `publishedAt` e `publishedBy` (o Publisher os preenche).

## 11.4 Índices e restrições

- `service_active_link` (único parcial, `WHERE lifecycle = 'present'`): no máximo uma ligação ativa por dono e serviço, mesmo
  com pedidos concorrentes.
- `lifecycle = 'absent'` exige `serviceRoles` vazio (restrição de tabela).
- `service_operation`: `(operation_status = 'rejected') = (operation_status_reason IS NOT NULL)` e
  `= (desired_generation IS NULL)`.
- `service_outbox_pending` (parcial, `published_at IS NULL`) e `service_outbox_published`; `message_id` único.
- Limites de tamanho e padrões nos identificadores, nas fases e nos estados (`CHECK`), e `jsonb` limitado a 256 KiB.

## 11.5 Quem grava o quê

Ver o mapa em [`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md) §9 e os privilégios em
`migrations/0001-service.sql`.

## 11.6 Dados pessoais no banco

Nenhum dado pessoal: só o ID do usuário no Zitadel (`owner_account_id`) e o nome do serviço. A linha de uma ligação desfeita
fica como histórico, sem dado adicional.

## 11.7 Consultas úteis (dev)

```sql
-- Ligações por fase e situação
SELECT phase, lifecycle, count(*) FROM sum.service GROUP BY 1, 2 ORDER BY 1, 2;

-- Atraso do outbox (idade da mensagem pendente mais antiga)
SELECT now() - min(created_at) AS atraso FROM sum.service_outbox WHERE published_at IS NULL;

-- Operations de um recurso
SELECT operation_id, operation_type, operation_status, operation_status_reason, desired_generation
  FROM sum.service_operation WHERE resource_id = '<resourceId>' ORDER BY created_at;
```
