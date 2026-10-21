# Como começar uma feature

> **Responsabilidade:** o roteiro para criar uma feature nova (`features/<módulo>/<tipo>`): o que gerar, o que copiar e ajustar, o que registrar fora da pasta da feature e como verificar. Não repete as regras: cada passo aponta para a fonte da verdade do tema.

Uma feature é **um tipo de recurso** (por exemplo, `core/account`, `ipm/organization`, `sum/service`) que segue o loop de controle de recursos: um projeto Python, uma imagem e seis contêineres, um por papel (decisão `0063`). `<módulo>` é o domínio (`core`, `ipm`, `sum`); `<tipo>` é o recurso (`account`, `organization`, `service`).

Nomes derivados, usados abaixo: pacote `<módulo>_<tipo>` · projeto e contêineres `<módulo>-<tipo>` · variáveis `<MÓDULO>_<TIPO>_` · recurso `<módulo>.<tipo>`.

## 1. Escolha o modelo mais próximo

O que é da regra de negócio do recurso (`domain/`, `service_rules.py`, `executor/actions/`, a lógica do Manager e do Reconciler) é **copiado e ajustado** de uma feature existente. Escolha pela forma do recurso:

| Se o recurso... | Copie de | Motivo |
|---|---|---|
| tem identidade própria no provedor de identidade e proteção contra exclusão | `core/account` | a mais completa e documentada (referência de toda a estrutura) |
| é uma entidade simples ligada a uma Organization | `ipm/organization` | o mesmo molde, com outra regra de negócio (também tem proteção contra exclusão) |
| é uma ligação ou concessão entre recursos, com catálogo | `sum/service` | tem catálogo e regras de dependência (`common/service_rules.py`) |
| vive dentro de uma Organization e age só nela (pessoas, com roles) | `ipm/user` | escopo por Organization, consulta a outro Receiver com o token de quem pede, catálogo do Grant e regra do `bind` (decisão 0077); nasce desprotegido, por exceção |

O que é igual em todas as features **não é copiado à mão**: vem do template (passo 3) e da semente (`--new`).

Todo recurso que pode ser apagado de verdade **nasce protegido** (`deletionProtection: true` no `desired`, decisão `0043`; a exceção registrada é o `ipm/user`, decisão `0077`), e a proteção é **campo gerenciado**: gravada como metadado `deletionProtection` no provedor e reconciliada (decisão `0074`). No schema, `x-managed: true` no `desired` e o campo opcional no `observed`.

## 2. Contrato primeiro

1. Defina os schemas do recurso em `schemas/<módulo>/<tipo>/` (`resource`, `desired`, `observed`, `requested-create|update|delete`, `api-*`, `definitions`, com exemplos) e o índice `schemas/<módulo>.<tipo>.index.json`. Regras em [`SCHEMA.md`](SCHEMA.md); mensagens e envelope em [`MESSAGING.md`](MESSAGING.md).
2. Rode os testes de `schemas/` (`cd schemas && uv run pytest`): validam os exemplos contra os schemas.

## 3. Crie o projeto

1. Crie a feature a partir do template (`<módulo>` e `<tipo>` são uma palavra em minúsculas, sem hífen):

   ```bash
   python templates/feature/sync.py --new <módulo> <tipo>
   ```

   Cria a pasta e grava duas coisas: a **semente** (`templates/feature/seed/`: `pyproject.toml`, `compose.yaml`, `config.toml`, `.env.example` e os manifestos de `consumers/`, que a feature passa a ter como dela e ajusta) e as **cópias** do template (`files/` e os perfis). Recusa nome inválido e feature que já existe.
2. Ajuste o que a semente não sabe: em `pyproject.toml`, as dependências do recurso (por exemplo `pydantic[email]` se o schema tiver `format: email`); em `compose.yaml` e `.env.example`, os papéis que o recurso não tem (o `core/account` e o `ipm/organization` têm Observer e Executor com identidade; o `sum/service` tem consumers a mais) e a audience do projeto de roles.
3. Gere o que depende do contrato, depois do índice do passo 2:

   ```bash
   cd features/<módulo>/<tipo> && uv lock && uv run datamodel-codegen   # modelos Pydantic dos schemas (decisão 0012)
   ```

   Arquivos gerados não são editados à mão (AGENTS §22): altere a fonte e gere de novo. Depois de alterar o template, rode `python templates/feature/sync.py` para regravar as cópias.
4. `sonar-project.properties` vem do template: confira a chave e o nome ([`.opencode/agents/sonarqube.md`](../.opencode/agents/sonarqube.md)).

O que o template grava: `common/` (inclusive `resource.py` e `logging_config.py`), testes comuns (inclusive `test_http_server.py`, `test_outbox_publisher.py` e `test_tolerant_reader.py`), o Publisher, o `openapi.py` e o `trace_context.py` do Receiver, os `streams.py` do Reconciler, a suíte e2e base (`tests/e2e/tests/contracts.py`), `Dockerfile`, `.dockerignore`, `sonar-project.properties` e `telemeter/` (decisões 0046, 0064 e 0065).

Os perfis opcionais trazem os motores e os módulos sem regra do tipo (decisões `0064` e [`0075`](../.decisions/0075-motores-identicos-gerados-do-template.md)). Uma feature nova começa sem nenhum. **Se ela segue um modelo que declara os perfis** (`core/account` ou `ipm/organization`), declare os mesmos perfis logo depois do `--new`, acrescentando `"<módulo>/<tipo>"` a cada tupla de `PROFILES` em `templates/feature/sync.py`, e rode `python templates/feature/sync.py`. Os motores chegam do template, e o que falta escrever é o contrato de cada perfil, na tabela abaixo. O `uv run pyright` lista o que ainda não existe (`Import ... could not be resolved`), e a lista zera quando o contrato está completo. Se um papel do recurso precisar de um motor diferente, não declare o perfil dele: a feature escreve o seu e registra a divergência numa decisão.

| Perfil | O que o template grava | O que a feature escreve (contrato) |
|---|---|---|
| `receiver-http` | `receiver/http/health_routes.py`, `submission.py` e `receiver/domain/{errors,records,requests}.py` | `receiver/http/app.py` (com `Dependencies` e `create_app`, usado pelo `openapi.py`), o restante do Receiver no molde do modelo |
| `manager-handlers` | `manager/domain/{convergence,errors,outcome}.py` e `manager/handlers/{envelope,observed,publishing,result}.py` | `manager/domain/kind.py` (`ResourceKind`, com `removes_absent`: `False` quando a remoção convergida mantém o registro, como no `sum/service`, decisão [`0080`](../.decisions/0080-manager-do-sum-no-modelo-do-loop.md)), `manager/domain/policy.py` (`ResourcePolicy`, usado pela convergência), `manager/handlers/ports.py` (`Store`) e o store que o implementa (`manager/store/ssot.py` no modelo) com `observed_generation` (`lock_resource` a devolve; `save_observation(..., observed_generation=...)`), e a coluna na migração (passo 5) |
| `loop-engines` | `observer/engine/observer.py` (com o envio do `observedGeneration`), `executor/engine/executor.py`, `executor/domain/{revalidation,errors}.py` e o teste `tests/observer/unit/test_engine.py` | `observer/settings.py` com `<Tipo>ObserverSettings` (`partition` e `loop`), `observer/domain/observation.py` com `Drivers`, `Observation`, `observe` e `log_identifiers`, `executor/actions/<tipo>_actions.py` com `Drivers` e `execute` e `executor/domain/identity.py` com `ProviderError` |
| `identity-metadata` | `executor/drivers/metadata.py` e `observer/drivers/metadata.py`, com os testes | `executor/provider/identity.py` com `IdentityConnection.call(...)`, `observer/provider/identity.py` com `IdentityConnection.request(...)` e `json(...)`, `ProviderError` em `executor/domain/identity.py` e `observer/domain/identity.py`, e `executor/settings.py` e `observer/settings.py` com `IdentitySettings` (decisões `0073` e `0074`) |

## 4. Escreva os papéis

Em `src/<módulo>_<tipo>/` cada papel é um subpacote com `main.py`, `settings.py` e `domain/` puro: `receiver`, `manager`, `publisher`, `reconciler`, `observer`, `executor`. O que o loop exige de cada um está em [`RESOURCE-CONTROL-LOOP.md`](RESOURCE-CONTROL-LOOP.md) e [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md); a estrutura interna, no README da feature modelo.

- A regra de negócio fica em `domain/` (sem I/O); o isolamento é verificado por `tests/common/unit/test_domain_isolation.py` e `test_role_isolation.py`, que vêm do template.
- **Executor e Observer espelhados** (decisão [`0073`](../.decisions/0073-drivers-espelhados-no-executor-e-no-observer.md)): `provider/identity.py` é só a conexão autenticada (`IdentityConnection`), e `drivers/<sub-recurso>.py` tem um driver por sub-recurso do provedor, com o mesmo nome nos dois papéis (escrita no Executor, só leitura no Observer). As `actions/` do Executor e o `domain/observation.py` do Observer recebem um pacote `Drivers` montado no `main.py`.
- **Toda alteração percorre o loop** (decisão [`0072`](../.decisions/0072-toda-alteracao-percorre-o-loop-e-geracao-observada.md)): o Manager não conclui uma Operation no `requested` (só um pedido sem geração nova, com a geração vigente já confirmada); ela conclui quando a observação confirma a geração.
- **O Observer envia `observedGeneration`** no envelope `observed`: a geração do `desired` que ele conhecia **antes** de ler o provedor. Sem isso o Manager nunca confirma uma geração e toda Operation fica `accepted`. Com o perfil `loop-engines`, o motor e o teste que cobre essa regra vêm do template. Sem o perfil, a feature escreve o motor e o teste, no molde do template (`templates/feature/optional/loop-engines/`).
- Cada papel usa o seu papel de login no banco (`<módulo>_<tipo>_<papel>_login`) e a sua identidade no broker; o `command` do contêiner escolhe o papel.
- O `main.py` só monta as tarefas do papel dentro de `role_runtime` (`common/runtime.py`), que conecta ao broker, registra a saúde, supervisiona e encerra (drena o broker e fecha o que for registrado em `close_after`). O Publisher vem pronto do template; com os perfis do passo 3, chegam também os motores do Observer e do Executor, a convergência e os handlers do Manager e o domínio comum do Receiver. O restante dos papéis segue o molde do `core/account`.
- Variáveis de infraestrutura levam a **função** como prefixo (`DATABASE_`, `MESSAGING_`, `GATEWAY_`, `TELEMETRY_`...), não o produto (decisão [`0068`](../.decisions/0068-variaveis-de-infraestrutura-nomeadas-pela-funcao.md)).
- Variáveis: `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>` (`role_config`); senhas sem default. No compose, cada senha de papel é montada como arquivo em `/run/secrets/<VARIÁVEL>` (bloco `secrets:`, decisão [`0070`](../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md)); o manifesto não define a variável `*_PASSWORD`. Cada papel herda `RoleSettings` (CLI → ambiente → `config.toml` → arquivos de segredo → default, decisão [`0067`](../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md)); os valores de dev da feature ficam no `config.toml` (semente), tabela `[tool.<módulo>.<tipo>.<papel>.<seção>]`.
- Testes por feature (não vêm do template, porque dependem dos papéis e dos motores): `tests/common/unit/test_role_entrypoints.py` (um por feature, modelo no `core/account`) e os testes dos motores de cada papel. Sem eles a cobertura do código novo não passa o Quality Gate. Os testes de `http_server` e do `outbox_publisher` já vêm do template.

## 5. Banco de dados

1. Migrações em `migrations/` (`0001-<tipo>.sql`): tabela principal, `outbox`, `operation` e `action_result`, views e privilégios por papel. Modelo e regras em [`SSOT.md`](SSOT.md) e [`POSTGRESQL.md`](POSTGRESQL.md) (a tabela de exemplo de lá é a referência atual). **Não copie só o `0001` do modelo:** o modelo evoluiu em migrações aditivas, e o `0001` dele não tem o que veio depois. A `0001` da feature nova já nasce com o estado atual de todas, em especial a coluna `observed_generation` com o `CHECK (observed_generation IS NULL OR (observed_generation >= 1 AND observed_generation <= desired_generation))` (decisão `0072`), o motivo de rejeição `protected` (decisão `0043`) e a coluna `traceparent` do outbox (decisão `0055`). Confira contra todas as migrações do modelo (`migrations/*.sql`).
2. Papéis do módulo em `infrastructure/dev/database/bootstrap/<módulo>.sql` — só se o **módulo** é novo; para um tipo novo de módulo existente, acrescente o papel do tipo à lista do arquivo existente.

## 6. Mensageria

Os Streams (`REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT`, `UPDATED`) são da plataforma e já existem (`infrastructure/dev/messaging/bootstrap/`); uma feature nova **não cria Stream**. Ela declara os seus consumers duráveis em `consumers/*.json` (Manager: `requested`, `observed`, `result`; Executor: um por partição de `ACTION`), copiados do modelo. Regras em [`NATS.md`](NATS.md).

## 7. Identidade e acesso

- Um projeto de roles por módulo no provedor de identidade e contas de serviço do Observer e do Executor ([`.decisions/0032`](../.decisions/0032-projetos-de-roles-por-modulo-e-papel-sem-grant.md), [`0028`](../.decisions/0028-padrao-de-nomes-das-roles.md)). Módulo novo exige o projeto novo; tipo novo de módulo existente reutiliza o do módulo.
- Rota da API em `infrastructure/dev/gateway/bootstrap/adc.yaml`: **uma por tipo** (decisões `0015`, `0030`, `0052`), com a variável `SMARKEE_GATEWAY_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` em `infrastructure/dev/gateway/.env.example` e no `compose.yaml` do gateway.

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
- `PROFILES` em `templates/feature/sync.py`: os perfis da feature nova já foram declarados no passo 3. Confira que o contrato de cada um está completo (`pyright` sem import não resolvido). Uma feature existente só entra num perfil quando o código dela já é igual ao do modelo.

## 10. Documentação e registro

- `README.md` da feature (papéis, estrutura, banco, como rodar) e o `DATA-FLOW` ([`.decisions/0024`](../.decisions/0024-data-flow-por-feature.md)); diagramas em `docs/` da feature.
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

O template, a semente e os perfis cobrem o que é **idêntico** entre as features, inclusive os motores do Observer e do Executor e a convergência do Manager (medição de 2026-10-20, decisão [`0075`](../.decisions/0075-motores-identicos-gerados-do-template.md): gerar do template, sem biblioteca comum). Seguem manuais, porque têm regra do tipo: a regra de negócio, o motor e a decisão do Reconciler, o Manager fora do perfil `manager-handlers` (store, `requested`, consumers, política), as `actions` e os drivers do provedor, a observação, os `settings.py` e `main.py` dos papéis, o `app.py` do Receiver, `contracts/generated.py` (gerado do contrato), `service_rules.py`, as rotas do gateway e as entradas da telemetria. Quando uma feature nova repetir um deles, meça de novo e leve ao template pelo mesmo critério.
