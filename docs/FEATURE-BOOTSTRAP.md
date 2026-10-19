# Como começar uma feature

> **Responsabilidade:** o roteiro para criar uma feature nova (`features/<módulo>/<tipo>`): o que gerar, o que copiar e ajustar, o que registrar fora da pasta da feature e como verificar. Não repete as regras: cada passo aponta para a fonte da verdade do tema.

Uma feature é **um tipo de recurso** (por exemplo, `core/account`, `ipm/organization`, `sum/service`) que segue o loop de controle de recursos: um projeto Python, uma imagem e seis contêineres, um por papel (decisão `0063`). `<módulo>` é o domínio (`core`, `ipm`, `sum`); `<tipo>` é o recurso (`account`, `organization`, `service`).

Nomes derivados, usados abaixo: pacote `<módulo>_<tipo>` · projeto e contêineres `<módulo>-<tipo>` · variáveis `<MÓDULO>_<TIPO>_` · recurso `<módulo>.<tipo>`.

## 1. Escolha o modelo mais próximo

Hoje parte do trabalho é **copiar e ajustar** uma feature existente. Escolha pela forma do recurso:

| Se o recurso... | Copie de | Motivo |
|---|---|---|
| tem identidade própria no provedor de identidade e proteção contra exclusão | `core/account` | a mais completa e documentada (referência de toda a estrutura) |
| é uma entidade simples ligada a uma Organization | `ipm/organization` | o mesmo molde, com outra regra de negócio |
| é uma ligação ou concessão entre recursos, com catálogo | `sum/service` | tem catálogo e regras de dependência (`common/service_rules.py`) |

O que é igual em todas as features **não é copiado à mão**: vem do template (passo 3).

## 2. Contrato primeiro

1. Defina os schemas do recurso em `schemas/<módulo>/<tipo>/` (`resource`, `desired`, `observed`, `requested-create|update|delete`, `api-*`, `definitions`, com exemplos) e o índice `schemas/<módulo>.<tipo>.index.json`. Regras em [`SCHEMA.md`](SCHEMA.md); mensagens e envelope em [`MESSAGING.md`](MESSAGING.md).
2. Rode os testes de `schemas/` (`cd schemas && uv run pytest`): validam os exemplos contra os schemas.

## 3. Crie o projeto

1. Crie `features/<módulo>/<tipo>/` com um `pyproject.toml` copiado do modelo do passo 1. Ajuste: `name`, os seis `[project.scripts]` (`<módulo>-<tipo>-<papel>`), `module-name`, `[tool.coverage.run] source`, `extend-exclude` do ruff e, em `[tool.datamodel-codegen]`, o `input` (índice do passo 2), `output` e `base-class`.
2. Crie `src/<módulo>_<tipo>/common/resource.py` com `MODULE`, `RESOURCE_TYPE` e `SCHEMA_VERSION` (o que é da feature no `common/`).
3. Gere o que é comum, a partir das fontes únicas:

   ```bash
   python templates/feature/sync.py          # common/ (inclusive logging_config.py), testes comuns, Dockerfile, .dockerignore, telemeter/config.yaml (decisões 0046 e 0064)
   cd features/<módulo>/<tipo> && uv lock && uv run datamodel-codegen   # modelos Pydantic dos schemas (decisão 0012)
   ```

   Arquivos gerados não são editados à mão (AGENTS §22): altere a fonte e gere de novo.
4. Copie `sonar-project.properties` do modelo e troque a chave, o nome e o pacote ([`.opencode/agents/sonarqube.md`](../.opencode/agents/sonarqube.md)).

## 4. Escreva os papéis

Em `src/<módulo>_<tipo>/` cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro: `receiver`, `manager`, `publisher`, `reconciler`, `observer`, `executor`. O que o loop exige de cada um está em [`RESOURCE-CONTROL-LOOP.md`](RESOURCE-CONTROL-LOOP.md) e [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md); a estrutura interna, no README da feature modelo.

- A regra de negócio fica em `domain/` (sem I/O); o isolamento é verificado por `tests/common/unit/test_domain_isolation.py` e `test_role_isolation.py`, que vêm do template.
- Cada papel usa o seu papel de login no banco (`<módulo>_<tipo>_<papel>_login`) e a sua identidade no broker; o `command` do contêiner escolhe o papel.
- Variáveis: `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>`; senhas sem default.

## 5. Banco de dados

1. Migrações em `migrations/` (`0001-<tipo>.sql`): tabela principal, `outbox`, `operation` e `action_result`, views e privilégios por papel. Modelo e regras em [`SSOT.md`](SSOT.md) e [`POSTGRESQL.md`](POSTGRESQL.md).
2. Papéis do módulo em `infrastructure/dev/database/bootstrap/<módulo>.sql` — só se o **módulo** é novo; para um tipo novo de módulo existente, acrescente o papel do tipo à lista do arquivo existente.

## 6. Mensageria

Os Streams (`REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT`, `UPDATED`) são da plataforma e já existem (`infrastructure/dev/messaging/bootstrap/`); uma feature nova **não cria Stream**. Ela declara os seus consumers duráveis em `consumers/*.json` (Manager: `requested`, `observed`, `result`; Executor: um por partição de `ACTION`), copiados do modelo. Regras em [`NATS.md`](NATS.md).

## 7. Identidade e acesso

- Um projeto de roles por módulo no provedor de identidade e contas de serviço do Observer e do Executor ([`.decisions/0032`](../.decisions/0032-projetos-de-roles-por-modulo-e-papel-sem-grant.md), [`0028`](../.decisions/0028-padrao-de-nomes-das-roles.md)). Módulo novo exige o projeto novo; tipo novo de módulo existente reutiliza o do módulo.
- Rota da API em `infrastructure/dev/gateway/bootstrap/adc.yaml`: **uma por tipo** (decisões `0015`, `0030`, `0052`), com a variável `APISIX_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` em `infrastructure/dev/gateway/.env.example` e no `compose.yaml` do gateway.

## 8. Execução em dev

1. `compose.yaml` e `.env.example` da feature: copie do modelo e troque os nomes (imagem `smarkee-<módulo>-<tipo>`, os seis contêineres, `migrate`, `consumer` e `telemeter`). Reinicie o gateway depois de recriar contêineres (cache de DNS do APISIX).
2. Telemetria: acrescente as entradas da feature ao `infrastructure/dev/telemetry-router/config.yaml` (log por `smarkee.module` e `smarkee.resource.type`; trace por `apisix.service_name`; exportador para `<módulo>-<tipo>-telemeter`). O `telemeter/config.yaml` da feature vem do template. Arquitetura em [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md); logs em [`OBSERVABILITY.md`](OBSERVABILITY.md).
3. Suba com `docker compose up -d` na pasta da feature, depois da plataforma (`infrastructure/dev`).

## 9. Cliente e ferramentas

- CLI `sk`: comandos e contrato do módulo em `clients/cli/src/sk/features/<módulo>/` e `sk/commands/` ([`.decisions/0035`](../.decisions/0035-cli-em-ingles.md)).
- `scripts/dev/cleanup`: se o recurso criar dados em teste, acrescente o tipo em `model.py` (`Kind`) e os padrões de nome de teste.
- `scripts/dev/backup`: acrescente o que a feature guarda de novo (`.env`, volumes).

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

O template cobre o que é **idêntico** entre as features. Os motores dos papéis, os `compose.yaml`, o `pyproject.toml`, as rotas do gateway e as entradas da telemetria ainda são copiados e ajustados à mão. Gerá-los, ou extrair os motores para uma biblioteca comum, é uma decisão em aberto, a tomar antes da quarta feature ([`.decisions/0064`](../.decisions/0064-template-das-features-gerado-de-fonte-unica.md)).
