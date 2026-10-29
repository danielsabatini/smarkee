# Como começar uma feature

> **Responsabilidade:** o roteiro para criar uma feature nova (`features/<módulo>/<tipo>`): o que gerar, o que copiar e ajustar, o que registrar fora da pasta da feature e como verificar. Não repete as regras: cada passo aponta para a fonte da verdade do tema.

Uma feature é **um tipo de recurso** (por exemplo, `core/account`, `ipm/organization`, `sum/service`) que segue o loop de controle de recursos: um projeto Python, uma imagem e um contêiner por papel (decisão `0063`): `api`, `publisher` e, quando o recurso tem um provedor externo, `controller` (decisões `0096` e `0098`). `<módulo>` é o domínio (`core`, `ipm`, `sum`); `<tipo>` é o recurso (`account`, `organization`, `service`).

Nomes derivados, usados abaixo: pacote `<módulo>_<tipo>` · projeto e contêineres `<módulo>-<tipo>` · variáveis `<MÓDULO>_<TIPO>_` · recurso `<módulo>.<tipo>`.

## 1. Escolha o modelo mais próximo

O que é da regra de negócio do recurso (`api/domain/`, `common/service_rules.py`, `controller/domain/` e `controller/drivers/`) é **copiado e ajustado** de uma feature existente. Escolha pela forma do recurso (decisão `0098`, que também define os dois tipos de feature):

| Se o recurso... | Tipo | Copie de | Motivo |
|---|---|---|---|
| tem identidade no provedor de identidade e proteção contra exclusão | `external-reconciled` (`api` + `publisher` + `controller`) | `core/account` | o Controller observa o Zitadel, decide, age e reobserva numa só transação |
| vive dentro de uma Organization e age só nela (pessoas, com roles) | `external-reconciled` | `ipm/user` | escopo por Organization, projeções locais (`organization-projection`, `member-projection`), catálogo do Grant e regra do `bind` (decisão `0077`); nasce desprotegido, por exceção |
| é uma ligação ou concessão entre recursos, com catálogo | `external-reconciled` | `sum/service` | catálogo com rollout (decisão `0079`), regras de dependência e Controller que concede e revoga permissões |
| é uma entidade só do SSOT, sem provedor externo | `internal-state` (`api` + `publisher`) | `bsm/account` ou `ipm/role` | sem `controller`: a admissão da API já é o estado final |

O que é igual em todas as features **não é copiado à mão**: vem do template (passo 3) e da semente (`--new`). Entre features **não há chamada HTTP**: o que uma precisa saber de outra vem de uma **projeção local do Stream `DESIRED`** (decisão `0100`).

Todo recurso que pode ser apagado de verdade **nasce protegido** (`deletionProtection: true` no `desired`, decisão `0043`; a exceção registrada é o `ipm/user`, decisão `0077`), e a proteção é **campo gerenciado**: gravada como metadado `deletionProtection` no provedor e reconciliada (decisão `0074`). No schema, `x-managed: true` no `desired` e o campo opcional no `observed`.

## 2. Contrato primeiro

1. Defina os schemas do recurso em `schemas/<módulo>/<tipo>/` (`resource`, `desired`, `observed`, `api-*`, `definitions`, com exemplos (não há `requested-*`: a API síncrona não tem Operation, decisão `0098`)) e o índice `schemas/<módulo>.<tipo>.index.json`. Regras em [`SCHEMA.md`](../data/SCHEMA.md); mensagens e envelope em [`MESSAGING.md`](../messaging/MESSAGING.md).
2. Rode os testes de `schemas/` (`cd schemas && uv run pytest`): validam os exemplos contra os schemas.

## 3. Crie o projeto

1. Crie a feature a partir do template (`<módulo>` e `<tipo>` são uma palavra em minúsculas, sem hífen):

   ```bash
   python templates/feature/sync.py --new <módulo> <tipo>
   ```

   Cria a pasta e grava duas coisas: a **semente** (`templates/feature/seed/`: `pyproject.toml`, `compose.yaml`, `config.toml`, `.env.example` e `k8s/{base,overlays/dev}`, que a feature passa a ter como dela e ajusta) e as **cópias** do template (`files/` e os perfis). Recusa nome inválido e feature que já existe.
2. Ajuste o que a semente não sabe: em `pyproject.toml`, as dependências do recurso (por exemplo `pydantic[email]` se o schema tiver `format: email`); em `k8s/` (e `compose.yaml` / `.env.example`), o `controller` (remova `k8s/base/controller.yaml` e a referência em `k8s/base/kustomization.yaml`, bem como de `compose.yaml`, `.env.example` e `config.toml`, se o recurso é `internal-state`), as variáveis do catálogo e das projeções que o recurso usa e a audience do projeto de roles.
3. Gere o que depende do contrato, depois do índice do passo 2:

   ```bash
   cd features/<módulo>/<tipo> && uv lock && uv run datamodel-codegen   # modelos Pydantic dos schemas (decisão 0012)
   ```

   Arquivos gerados não são editados à mão (AGENTS §22): altere a fonte e gere de novo. Depois de alterar o template, rode `python templates/feature/sync.py` para regravar as cópias.
4. `sonar-project.properties` vem do template: confira a chave e o nome ([`.opencode/agents/sonarqube.md`](../../.opencode/agents/sonarqube.md)).

O que o template grava: `common/` (inclusive `resource.py` e `logging_config.py`), testes comuns (inclusive `test_http_server.py`, `test_outbox_publisher.py` e `test_tolerant_reader.py`), o Publisher, o `health_routes.py`, o `openapi.py` e o `trace_context.py` da API (perfil `api-http`), a suíte e2e base (`tests/e2e/tests/contracts.py`), `Dockerfile`, `.dockerignore`, `sonar-project.properties` e `telemeter/` (decisões 0046, 0064 e 0065).

Os perfis opcionais trazem módulos idênticos entre as features (decisões `0064` e [`0075`](../../.decisions/0075-motores-identicos-gerados-do-template.md)). Uma feature nova começa sem nenhum. Declare os que o recurso usa, acrescentando `"<módulo>/<tipo>"` à tupla de `PROFILES` em `templates/feature/sync.py` logo depois do `--new`, e rode `python templates/feature/sync.py --write`. Se o módulo do perfil precisar de um comportamento diferente, não declare o perfil: a feature escreve o seu e registra a divergência numa decisão.

| Perfil | O que o template grava | O que a feature escreve (contrato) |
|---|---|---|
| `api-http` (toda feature) | `api/http/health_routes.py`, `openapi.py`, `trace_context.py` e o teste do contexto de trace | `api/http/app.py` (com `Dependencies` e `create_app`, usado pelo `openapi.py`), `auth/`, `domain/`, `store/` e `main.py` da API |
| `organization-projection` | `api/transport/organization_projection.py` (dono e ciclo de vida das Organizations, pelo `DESIRED`) | o consumer e a ligação no `main.py` da API |
| `member-projection` | `api/transport/member_projection.py` (Organization de cada usuário e service account, pelo `DESIRED`) | o consumer e a ligação no `main.py` da API |

## 4. Escreva os papéis

Em `src/<módulo>_<tipo>/` cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro: `api`, `publisher` e, no tipo `external-reconciled`, `controller`. O que o loop exige de cada um está em [`RESOURCE-CONTROL-LOOP.md`](../loop/RESOURCE-CONTROL-LOOP.md) e [`RESOURCE-CONTROL-SECURITY.md`](../loop/RESOURCE-CONTROL-SECURITY.md); a decisão, em [`0098`](../../.decisions/0098-api-sincrona-e-fim-da-operation.md) e [`0096`](../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md); a estrutura interna, no README da feature modelo.

- A regra de negócio fica em `domain/` (sem I/O); o isolamento é verificado por `tests/common/unit/test_domain_isolation.py` e `test_role_isolation.py`, que vêm do template.
- **API síncrona** (decisão `0098`): autentica, autoriza, valida e admite a escrita **na requisição**, numa transação (recurso bloqueado, regras, escrita do recurso e `desired` no outbox). `POST` → `201`, `PATCH` → `200`, `DELETE` → `202`, sempre com o `Resource`; `409` por `resourceVersion`; `Idempotency-Key` em `<módulo>.<tipo>_idempotency`; `emitter = api`. Sem Operation e sem Stream `REQUESTED`: a convergência se lê no próprio recurso (`observedGeneration >= desiredGeneration` e `phase`).
- **Sem HTTP entre features** (decisão `0100`): precondições que dependem de outro tipo usam projeções locais do `DESIRED` (`api/transport/`); projeção ainda sincronizando é `503 ProjectionSyncPending`.
- **Controller** (decisão `0096`): consome o `DESIRED`, enfileira o `resourceId` (deduplicação e backoff) e, por recurso, executa o ciclo atômico observar → decidir → agir → reobservar, gravando estado, fase, conditions e `updated` no SSOT. Tem `drivers/` por sub-recurso do provedor; só ele apaga a linha do recurso.
- Cada papel usa o seu papel de login no banco (`<módulo>_<tipo>_<papel>_login`) e a sua identidade no broker; o `command` do contêiner escolhe o papel.
- O `main.py` só monta as tarefas do papel dentro de `role_runtime` (`common/runtime.py`), que conecta ao broker, registra a saúde, supervisiona e encerra (drena o broker e fecha o que for registrado em `close_after`). O Publisher vem pronto do template.
- Variáveis de infraestrutura levam a **função** como prefixo (`DATABASE_`, `MESSAGING_`, `GATEWAY_`, `TELEMETRY_`...), não o produto (decisão [`0068`](../../.decisions/0068-variaveis-de-infraestrutura-nomeadas-pela-funcao.md)).
- Variáveis: `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>` (`role_config`); senhas sem default. No compose, cada senha de papel é montada como arquivo em `/run/secrets/<VARIÁVEL>` (bloco `secrets:`, decisão [`0070`](../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md)); o manifesto não define a variável `*_PASSWORD`. Cada papel herda `RoleSettings` (CLI → ambiente → `config.toml` → arquivos de segredo → default, decisão [`0067`](../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md)); os valores de dev da feature ficam no `config.toml` (semente), tabela `[tool.<módulo>.<tipo>.<papel>.<seção>]`.
- Testes por feature (não vêm do template, porque dependem dos papéis): `tests/common/unit/test_role_entrypoints.py` (um por feature, modelo no `core/account`) e os testes de cada papel (`tests/api`, `tests/controller`, `tests/publisher/integration`). Sem eles a cobertura do código novo não passa o Quality Gate. Os testes de `http_server` e do `outbox_publisher` já vêm do template.

## 5. Banco de dados

1. Migrações em `migrations/` (`0001-<tipo>.sql`): tabela principal, `outbox` e `idempotency`, views e privilégios por papel (`<módulo>_<tipo>_{api,publisher,controller,maintenance}`; só o Controller apaga a linha do recurso). Sem `operation` nem `action_result`. Modelo e regras em [`SSOT.md`](../data/SSOT.md) e [`POSTGRESQL.md`](../data/POSTGRESQL.md) (a tabela de exemplo de lá é a referência atual). **Não copie só o `0001` do modelo:** o modelo evoluiu em migrações aditivas, e o `0001` dele não tem o que veio depois. A `0001` da feature nova já nasce com o estado atual de todas, em especial a coluna `observed_generation` com o `CHECK (observed_generation IS NULL OR (observed_generation >= 1 AND observed_generation <= desired_generation))` (decisão `0072`), o motivo de rejeição `protected` (decisão `0043`) e a coluna `traceparent` do outbox (decisão `0055`). Confira contra todas as migrações do modelo (`migrations/*.sql`).
2. Papéis do módulo em `infrastructure/dev/database/bootstrap/<módulo>.sql` — só se o **módulo** é novo; para um tipo novo de módulo existente, acrescente o papel do tipo à lista do arquivo existente.

## 6. Mensageria

Os Streams (`DESIRED` e `UPDATED`, entre outros) são da plataforma e já existem (`infrastructure/dev/messaging/bootstrap/`); uma feature nova **não cria Stream**. O Controller e as projeções da API criam os próprios consumers duráveis na partida (decisões `0096` e `0100`), então a feature não tem pasta `consumers/`. Regras em [`NATS.md`](../messaging/NATS.md).

## 7. Identidade e acesso

- Um projeto de roles por módulo no provedor de identidade e a conta de serviço do Controller (`<módulo>-<tipo>-controller`, quando o recurso usa o Zitadel; [`.decisions/0032`](../../.decisions/0032-projetos-de-roles-por-modulo-e-papel-sem-grant.md), [`0028`](../../.decisions/0028-padrao-de-nomes-das-roles.md)). Módulo novo exige o projeto novo; tipo novo de módulo existente reutiliza o do módulo.
- Rota da API em `infrastructure/k8s/platform/gateway/base/configmap.yaml` (e `infrastructure/dev/gateway/bootstrap/adc.yaml`): **uma por tipo** (decisões `0015`, `0030`, `0052`, `0102`), com a variável `SMARKEE_GATEWAY_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` em `infrastructure/k8s/platform/gateway/base/external-secret.yaml`, `infrastructure/k8s/platform/gateway/base/deployment.yaml` e `scripts/dev/vault-bootstrap` (`svm/data/platform/gateway`).

## 8. Execução em dev (Kubernetes + GitOps)

1. `k8s/{base,overlays/dev}`, `compose.yaml` e `.env.example` da feature vêm da semente (passo 3), com a imagem `localhost:5001/smarkee-<módulo>-<tipo>:dev`, os `Deployment`s dos papéis (`api`, `publisher`, `controller`), o `Job` `migrate`, o `OpenTelemetryCollector` `telemeter` e o `ExternalSecret` que lê `/svm/data/features/<módulo>/<tipo>` no `vault` (decisão `0102`); ajuste ao recurso e registre os segredos da feature em `scripts/dev/vault-bootstrap`.
2. ArgoCD: crie `infrastructure/k8s/argocd/features/<módulo>-<tipo>.yaml` e acrescente-o a `infrastructure/k8s/argocd/features/kustomization.yaml` (Wave 4).
3. Telemetria: acrescente as entradas da feature ao `infrastructure/k8s/platform/telemetry/base/telemetry-router.yaml` (e `infrastructure/dev/telemetry-router/config.yaml`: log por `smarkee.module` e `smarkee.resource.type`; trace por `apisix.service_name == "<módulo>-<tipo>-api"`; exportador para `<módulo>-<tipo>-telemeter-collector.<módulo>.svc.cluster.local:4317`) e à suíte `tests/telemetry/tests/test_telemetry.py` (`FEATURE_TELEMETRY_DIRS`, `FEATURE_ROUTES` e `outbox_collections`). O `telemeter/config.yaml` e `k8s/base/telemeter.yaml` da feature vêm do template/semente. Arquitetura em [`OBSERVABILITY-ARCHITECTURE.md`](../telemetry/OBSERVABILITY-ARCHITECTURE.md); logs em [`OBSERVABILITY.md`](../telemetry/OBSERVABILITY.md).
4. Construa e publique a imagem com `./scripts/dev/build-push <módulo>/<tipo>` e sincronize no cluster (`./scripts/dev/cluster-up`).

## 9. Cliente e ferramentas

- CLI `sk`: comandos e contrato do módulo em `clients/cli/src/sk/features/<módulo>/` e `sk/commands/` ([`.decisions/0035`](../../.decisions/0035-cli-em-ingles.md)).
- `scripts/dev/cleanup`: se o recurso criar dados em teste, acrescente o tipo em `model.py` (`Kind`) e os padrões de nome de teste.
- `scripts/dev/backup`: acrescente o que a feature guarda de novo (`.env`, volumes): o `.env` em `ENV_FILES` e a pasta em `FEATURE_DIRECTORIES` (`model.py`).
- `.gitignore`: nada a fazer; a regra da saída do telemeter vale para qualquer `features/<módulo>/<tipo>` (decisão `0062`).
- `infrastructure/dev/identity/conformance/tests/test_structure.py`: acrescente a feature a `ENV_FILES`, `EXPECTED_AUDIENCE` (e, se houver conta de serviço do Controller, `EXPECTED_REGISTER` e `EXPECTED_PROJECT_IDS`), para o desvio de configuração ser detectado (decisão `0037`).
- `PROFILES` em `templates/feature/sync.py`: os perfis da feature nova já foram declarados no passo 3. Confira que o contrato de cada um está completo (`pyright` sem import não resolvido). Uma feature existente só entra num perfil quando o código dela já é igual ao do modelo.
- `scripts/dev/republish`: acrescente o tipo em `model.py` (`Kind`, com o papel de login da API, que escreve o outbox).

## 10. Documentação e registro

- `README.md` da feature (papéis, estrutura, banco, como rodar) e o `DATA-FLOW` ([`.decisions/0024`](../../.decisions/0024-data-flow-por-feature.md)); diagramas em `docs/` da feature.
- `docs/CONFIGURATION.md` (guia de parâmetros: precedência, campos e execução de cada papel). É **gerado** dos `settings.py` pelo template, depois que os papéis existem: `cd features/<módulo>/<tipo> && uv run python ../../../templates/feature/configuration_guide.py`. Não se edita à mão, e o teste `tests/common/unit/test_configuration_guide.py` falha quando ele diverge dos `settings.py`.
- Decisão em `.decisions/` se houver escolha relevante; atualize [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md) e, no que for do produto, o `CHANGELOG.md` e o `ROADMAP.md` (AGENTS §36.3, §37, §38).

## 11. Verificação antes de avançar

```bash
python templates/feature/sync.py --check
cd features/<módulo>/<tipo>
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/*/unit tests/*/contract          # integração e e2e pedem a stack de dev no ar
```

Depois: análise do SonarQube (Quality Gate e cobertura acima de 80%) e o e2e do tipo (`tests/e2e/`), seguido de `smarkee-dev-cleanup`.

## O que ainda é manual

O template, a semente e os perfis cobrem o que é **idêntico** entre as features (decisão [`0075`](../../.decisions/0075-motores-identicos-gerados-do-template.md): gerar do template, sem biblioteca comum). Seguem manuais, porque têm regra do tipo: a regra de negócio, o `app.py`, a admissão e o store da API, a decisão, os drivers e o store do Controller, os `settings.py` e `main.py` dos papéis, `contracts/generated.py` (gerado do contrato), `service_rules.py`, as rotas do gateway e as entradas da telemetria. Quando uma feature nova repetir um deles, meça de novo e leve ao template pelo mesmo critério.
