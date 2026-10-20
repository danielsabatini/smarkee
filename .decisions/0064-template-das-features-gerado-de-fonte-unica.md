# 0064 — Template das features gerado de fonte única

- **Data:** 2026-10-19
- **Status:** Aceita e implementada. Estende a 0046 (que cobria só o formatter de logs) ao restante do que é idêntico entre as features, e prepara a criação de novas features.

## Contexto

A auditoria do `core/account` (2026-10-19), com as três features em uma imagem cada (0063), mediu que o `common/` (10 arquivos), cinco testes de `tests/common/unit`, o `Dockerfile`, o `.dockerignore` e o `telemeter/config.yaml` são idênticos nas três features, exceto pelo nome. Criar uma feature nova significava copiar e renomear à mão, e as cópias já tinham começado a divergir (docstrings em `messaging.py` e `ids.py`).

## Decisão

- **Fonte única** em `templates/feature/files/`: o modelo de cada arquivo, com marcadores no lugar dos nomes da feature (`@@PACKAGE@@`, `@@KEBAB@@`, `@@UPPER@@`, `@@DOTTED@@`, `@@MODULE@@`; no caminho, o diretório `PACKAGE`).
- **`templates/feature/sync.py`** (só biblioteca padrão) grava as cópias em cada `features/<módulo>/<tipo>/` ou, com `--check`, as confere. Um teste em `schemas/tests/test_feature_template.py` falha se alguma cópia divergir.
- **Cada feature continua com os seus arquivos**: sem dependência de runtime entre features nem biblioteca interna, e o contexto de build do Docker não muda (a 0046 e a 0063 se mantêm).
- **Fora do template** (é da feature): `common/resource.py`, `common/contracts/generated.py`, `service_rules.py`, `pyproject.toml`, `compose.yaml`, `.env.example`, `sonar-project.properties` e tudo dos papéis (`receiver/`, `manager/`, etc.).
- **Uma feature nova**: criar o `pyproject.toml` e o `resource.py`, rodar `python templates/feature/sync.py` e escrever os papéis.
- Para alterar o template: editar o modelo, rodar o `sync.py` e a suíte de cada feature (AGENTS §22).

## Consequências

- Divergência vira falha de teste, e uma correção no `common/` ou nos testes comuns é feita uma vez.
- Os motores dos papéis (Publisher, Reconciler, handlers do Manager), 96 a 100% idênticos entre `core/account` e `ipm/organization`, **não** entram: variam entre features (`sum`) e a escolha entre geração e biblioteca comum fica para uma decisão própria antes da quarta feature.
- Nesta decisão, só `ids.py` e a docstring de `messaging.py` mudaram de texto nas cópias existentes; nenhum comportamento mudou.

## Ajuste (2026-10-19): o formatter de logs também vive no template

O `logging_config.py` e o `test_logging.py`, que a 0046 mantinha em `schemas/observability/python/` com um `sync.py` próprio, passaram para `templates/feature/files/`, e o `schemas/observability/sync.py` foi removido. `schemas/observability/` guarda só o contrato (o schema da linha de log e o exemplo), e toda geração de código fica em `templates/`. A 0046 continua valendo no que decide (fonte única, cópias geradas e conferidas); mudou onde a fonte mora e qual script a grava.

## Ajuste (2026-10-19): semente, `--new` e mais arquivos no template

Uma nova medição (arquivos comparados entre as três features, com os nomes normalizados) mostrou mais arquivos idênticos, e que `pyproject.toml`, `compose.yaml`, `.env.example` e `consumers/` são iguais a menos do nome e de poucas linhas por recurso.

- **Entram em `files/`** (idênticos nas três): `common/resource.py`, `sonar-project.properties`, `receiver/http/openapi.py` e `trace_context.py`, `reconciler/transport/streams.py`, `telemeter/{logs,traces}/.gitkeep`, `tests/common/unit/test_tolerant_reader.py`, `tests/e2e/tests/contracts.py` e `tests/receiver/unit/test_trace_context.py`.
- **Perfil `manager-handlers`** (`core/account` e `ipm/organization`): `manager/domain/outcome.py` e `manager/handlers/{envelope,observed,publishing,result}.py`. O `sum/service` tem outro Manager e não o declara.
- **Semente** (`templates/feature/seed/`): `pyproject.toml`, `compose.yaml`, `.env.example` e `consumers/*.json`. Diferem entre features em poucas linhas, então não são mantidos pelo `sync.py`: o `--new <módulo> <tipo>` os grava **uma vez** (e recusa feature existente), e a feature passa a ser dona deles. O `--check` não os cobre, de propósito.
- **Escopo do `--new`:** cria só a pasta da feature. Não altera arquivos compartilhados (gateway, telemetria, bootstrap do banco, CLI, `scripts/dev`): são o passo 9 do roteiro.
- **`.gitignore`** passa a ter uma regra única para `features/*/*/telemeter/`, no lugar de uma por feature.
- **Continua em aberto** gerar ou extrair os motores do Reconciler, do Executor e do Observer, os `settings.py` e `main.py`: a medição entre `core/account` e `ipm/organization` mostrou cerca de 85% de linhas iguais, mas as diferenças estão dentro dos motores (`receiver/http/app.py`, `executor/provider/identity.py`, `observer/domain/observation.py`), e extrair agora fixaria uma divisão sem evidência da quarta feature (§6, §25).

## Ajuste (2026-10-20): questão dos motores fechada pela 0075

A escolha que ficou "em aberto" (gerar ou extrair os motores) foi fechada pela decisão 0075: o que é idêntico entre as features, inclusive os motores do Observer e do Executor e a convergência do Manager, vai para o template como perfil (`loop-engines`, e `receiver-http` ampliado), sem biblioteca comum. O que tem regra do tipo continua na feature.
