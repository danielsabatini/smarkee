# Como começar uma feature

> **Responsabilidade:** o roteiro para criar uma feature nova (`features/<módulo>/<tipo>`): o que gerar, o que copiar e ajustar, o que registrar fora da pasta da feature e como verificar. Não repete as regras: cada passo aponta para a fonte da verdade do tema.

Uma feature é **um tipo de recurso** (por exemplo, `core/account`, `ipm/organization`, `sum/service`) que segue o loop de controle de recursos: um projeto Python, uma imagem e seis contêineres, um por papel (decisão `0063`). `<módulo>` é o domínio (`core`, `ipm`, `sum`); `<tipo>` é o recurso (`account`, `organization`, `service`).

Nomes derivados, usados abaixo: pacote `<módulo>_<tipo>` · projeto e contêineres `<módulo>-<tipo>` · variáveis `<MÓDULO>_<TIPO>_` · recurso `<módulo>.<tipo>`.

## 1. Escolha o modelo mais próximo

O que é da regra de negócio do recurso (`domain/`, `service_rules.py`, `executor/actions/`, a lógica do Manager e do Reconciler) é **copiado e ajustado** de uma feature existente. Escolha pela forma do recurso:

| Se o recurso... | Copie de | Motivo |
|---|---|---|
| tem identidade própria no provedor de identidade e proteção contra exclusão | `core/account` | a mais completa e documentada (referência de toda a estrutura) |
| é uma entidade simples ligada a uma Organization | `ipm/organization` | o mesmo molde, com outra regra de negócio |
| é uma ligação ou concessão entre recursos, com catálogo | `sum/service` | tem catálogo e regras de dependência (`common/service_rules.py`) |

O que é igual em todas as features **não é copiado à mão**: vem do template (passo 3) e da semente (`--new`).

## 2. Contrato primeiro

1. Defina os schemas do recurso em `schemas/<módulo>/<tipo>/` (`resource`, `desired`, `observed`, `requested-create|update|delete`, `api-*`, `definitions`, com exemplos) e o índice `schemas/<módulo>.<tipo>.index.json`. Regras em [`SCHEMA.md`](SCHEMA.md); mensagens e envelope em [`MESSAGING.md`](MESSAGING.md).
2. Rode os testes de `schemas/` (`cd schemas && uv run pytest`): validam os exemplos contra os schemas.

## 3. Crie o projeto

1. Crie a feature a partir do template (`<módulo>` e `<tipo>` são uma palavra em minúsculas, sem hífen):

   ```bash
   python templates/feature/sync.py --new <módulo> <tipo>
   ```

   Cria a pasta e grava duas coisas: a **semente** (`templates/feature/seed/`: `pyproject.toml`, `compose.yaml`, `.env.example` e os manifestos de `consumers/`, que a feature passa a ter como dela e ajusta) e as **cópias** do template (`files/` e os perfis). Recusa nome inválido e feature que já existe.
2. Ajuste o que a semente não sabe: em `pyproject.toml`, as dependências do recurso (por exemplo `pydantic[email]` se o schema tiver `format: email`); em `compose.yaml` e `.env.example`, os papéis que o recurso não tem (o `core/account` e o `ipm/organization` têm Observer e Executor com identidade; o `sum/service` tem consumers a mais) e a audience do projeto de roles.
3. Gere o que depende do contrato, depois do índice do passo 2:

   ```bash
   cd features/<módulo>/<tipo> && uv lock && uv run datamodel-codegen   # modelos Pydantic dos schemas (decisão 0012)
   ```

   Arquivos gerados não são editados à mão (AGENTS §22): altere a fonte e gere de novo. Depois de alterar o template, rode `python templates/feature/sync.py` para regravar as cópias.
4. `sonar-project.properties` vem do template: confira a chave e o nome ([`.opencode/agents/sonarqube.md`](../.opencode/agents/sonarqube.md)).

O que o template grava: `common/` (inclusive `resource.py` e `logging_config.py`), testes comuns (inclusive `test_http_server.py`, `test_outbox_publisher.py` e `test_tolerant_reader.py`), o Publisher, o `openapi.py` e o `trace_context.py` do Receiver, os `streams.py` do Reconciler, a suíte e2e base (`tests/e2e/tests/contracts.py`), `Dockerfile`, `.dockerignore`, `sonar-project.properties` e `telemeter/` (decisões 0046, 0064 e 0065). Os perfis `receiver-http` e `manager-handlers` entram nas features que os declaram em `PROFILES`.

## 4. Escreva os papéis

Em `src/<módulo>_<tipo>/` cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro: `receiver`, `manager`, `publisher`, `reconciler`, `observer`, `executor`. O que o loop exige de cada um está em [`RESOURCE-CONTROL-LOOP.md`](RESOURCE-CONTROL-LOOP.md) e [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md); a estrutura interna, no README da feature modelo.

- A regra de negócio fica em `domain/` (sem I/O); o isolamento é verificado por `tests/common/unit/test_domain_isolation.py` e `test_role_isolation.py`, que vêm do template.
- Cada papel usa o seu papel de login no banco (`<módulo>_<tipo>_<papel>_login`) e a sua identidade no broker; o `command` do contêiner escolhe o papel.
- O `main.py` só monta as tarefas do papel dentro de `role_runtime` (`common/runtime.py`), que conecta ao broker, registra a saúde, supervisiona e encerra (drena o broker e fecha o que for registrado em `close_after`). O Publisher vem pronto do template, e o Manager traz do perfil `manager-handlers` o envelope e a persistência de `observed` e do resultado; o restante dos papéis segue o molde do `core/account`.
- Variáveis de infraestrutura levam a **função** como prefixo (`DATABASE_`, `MESSAGING_`, `GATEWAY_`, `TELEMETRY_`...), não o produto (decisão [`0068`](../.decisions/0068-variaveis-de-infraestrutura-nomeadas-pela-funcao.md)).
- Variáveis: `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>` (`role_config`); senhas sem default. Cada papel herda `RoleSettings` (CLI → ambiente → `config.toml` → arquivos de segredo → default, decisão [`0067`](../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md)); os valores de dev da feature ficam no `config.toml` (semente), tabela `[tool.<módulo>.<tipo>.<papel>.<seção>]`.
- Testes por feature (não vêm do template, porque dependem dos papéis e dos motores): `tests/common/unit/test_role_entrypoints.py` (um por feature, modelo no `core/account`) e os testes dos motores de cada papel. Sem eles a cobertura do código novo não passa o Quality Gate. Os testes de `http_server` e do `outbox_publisher` já vêm do template.

## 5. Banco de dados

1. Migrações em `migrations/` (`0001-<tipo>.sql`): tabela principal, `outbox`, `operation` e `action_result`, views e privilégios por papel. Modelo e regras em [`SSOT.md`](SSOT.md) e [`POSTGRESQL.md`](POSTGRESQL.md).
2. Papéis do módulo em `infrastructure/dev/database/bootstrap/<módulo>.sql` — só se o **módulo** é novo; para um tipo novo de módulo existente, acrescente o papel do tipo à lista do arquivo existente.

## 6. Mensageria

Os Streams (`REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT`, `UPDATED`) são da plataforma e já existem (`infrastructure/dev/messaging/bootstrap/`); uma feature nova **não cria Stream**. Ela declara os seus consumers duráveis em `consumers/*.json` (Manager: `requested`, `observed`, `result`; Executor: um por partição de `ACTION`), copiados do modelo. Regras em [`NATS.md`](NATS.md).

## 7. Identidade e acesso

- Um projeto de roles por módulo no provedor de identidade e contas de serviço do Observer e do Executor ([`.decisions/0032`](../.decisions/0032-projetos-de-roles-por-modulo-e-papel-sem-grant.md), [`0028`](../.decisions/0028-padrao-de-nomes-das-roles.md)). Módulo novo exige o projeto novo; tipo novo de módulo existente reutiliza o do módulo.
- Rota da API em `infrastructure/dev/gateway/bootstrap/adc.yaml`: **uma por tipo** (decisões `0015`, `0030`, `0052`), com a variável `GATEWAY_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` em `infrastructure/dev/gateway/.env.example` e no `compose.yaml` do gateway.

## 8. Execução em dev

1. `compose.yaml` e `.env.example` da feature vêm da semente (passo 3), com a imagem `smarkee-<módulo>-<tipo>`, os seis contêineres, `migrate`, `consumer` e `telemeter`; ajuste ao recurso. Reinicie o gateway depois de recriar contêineres (cache de DNS do APISIX).
2. Telemetria: acrescente as entradas da feature ao `infrastructure/dev/telemetry-router/config.yaml` (log por `smarkee.module` e `smarkee.resource.type`; trace por `apisix.service_name`; exportador para `<módulo>-<tipo>-telemeter`). O `telemeter/config.yaml` da feature vem do template. Arquitetura em [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md); logs em [`OBSERVABILITY.md`](OBSERVABILITY.md).
3. Suba com `docker compose up -d` na pasta da feature, depois da plataforma (`infrastructure/dev`).

## 9. Cliente e ferramentas

- CLI `sk`: comandos e contrato do módulo em `clients/cli/src/sk/features/<módulo>/` e `sk/commands/` ([`.decisions/0035`](../.decisions/0035-cli-em-ingles.md)).
- `scripts/dev/cleanup`: se o recurso criar dados em teste, acrescente o tipo em `model.py` (`Kind`) e os padrões de nome de teste.
- `scripts/dev/backup`: acrescente o que a feature guarda de novo (`.env`, volumes): o `.env` em `ENV_FILES` e a pasta em `FEATURE_DIRECTORIES` (`model.py`).
- `.gitignore`: nada a fazer; a regra da saída do telemeter vale para qualquer `features/<módulo>/<tipo>` (decisão `0062`).
- `infrastructure/dev/identity/conformance/tests/test_structure.py`: acrescente a feature a `ENV_FILES`, `EXPECTED_AUDIENCE` (e, se houver contas de serviço do Observer e do Executor, `EXPECTED_REGISTER` e `EXPECTED_PROJECT_IDS`), para o desvio de configuração ser detectado (decisão `0037`).
- `PROFILES` em `templates/feature/sync.py`: declare `receiver-http` e `manager-handlers` somente se o código da feature for igual ao do modelo. Se não for, não declare: a feature segue com o seu código.

## 10. Documentação e registro

- `README.md` da feature (papéis, estrutura, banco, como rodar) e o `DATA-FLOW` ([`.decisions/0024`](../.decisions/0024-data-flow-por-feature.md)); diagramas em `docs/` da feature.
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

O template e a semente cobrem o que é **idêntico** entre as features (medido em 2026-10-19: o restante varia por recurso). Seguem manuais, porque diferem entre as features: a regra de negócio, os motores do Reconciler, do Executor e do Observer, os `settings.py` e `main.py` dos papéis, `contracts/generated.py` (gerado do contrato), `service_rules.py`, as rotas do gateway e as entradas da telemetria. Gerá-los, ou extrair os motores para uma biblioteca comum, continua sendo a decisão em aberto da [`.decisions/0064`](../.decisions/0064-template-das-features-gerado-de-fonte-unica.md), a tomar com evidência de que a quarta feature repete os motores.
