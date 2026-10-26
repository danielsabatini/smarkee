---
description: Python Engineering — padrão de desenvolvimento, tooling, packaging e qualidade para Python 3.14
mode: subagent
permissions:
  - action: edit
    resource: "*"
    effect: deny
  - action: shell
    resource: "*"
    effect: deny
---

# Python Engineering

Este agent é responsável pelas convenções e práticas específicas de engenharia Python do projeto.

Este arquivo é a fonte da verdade para:

- Python
- Packaging Python
- Gerenciamento de dependências
- Tooling Python
- Type checking
- Linting
- Formatação
- Testes Python
- Coverage

As regras gerais de comportamento dos agentes permanecem definidas no `AGENTS.md`.

---

# 1. Python

A versão padrão do projeto é:

```text
Python 3.14
```

Ao revisar este arquivo, confirme se a versão estável mais recente ainda é a adotada (`AGENTS.md`, seção 24.2).

O código deve utilizar as capacidades modernas do Python 3.14 quando elas melhorarem:

- Clareza
- Tipagem
- Segurança
- Legibilidade
- Manutenibilidade
- Simplicidade

Não introduza compatibilidade com versões anteriores do Python sem requisito explícito.

Quanto a APIs e padrões legados da linguagem e das bibliotecas, siga `AGENTS.md`, seção 24.2.

A modernidade da linguagem não deve ser utilizada como justificativa para aumentar a complexidade.

---

# 2. uv

**uv** é o padrão para gerenciamento do ecossistema Python.

Utilize uv para:

- Gerenciamento de projetos.
- Gerenciamento de dependências.
- Criação e sincronização de ambientes.
- Execução de comandos.
- Execução de ferramentas.
- Resolução de dependências.
- Lock de dependências.
- Gerenciamento de workspaces.
- Build de pacotes Python.

Preferir:

```text
uv add
uv remove
uv sync
uv run
uv lock
uv build
```

Não utilize mecanismos alternativos de gerenciamento de dependências para o mesmo projeto sem uma necessidade concreta.

O `pyproject.toml` é a fonte principal de configuração do projeto Python.

O lockfile gerenciado pelo uv deve ser utilizado para garantir reprodutibilidade das dependências.

## 2.1 Build Backend

**`uv_build`** é o build backend padrão para os projetos Python.

Utilize:

```toml
[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
```

Não utilize outro build backend sem uma necessidade concreta.

O build deve ser realizado através do uv:

```text
uv build
```

---

# 3. Estrutura Python

Projetos Python devem utilizar, por padrão, `src layout`:

```text
project/
├── pyproject.toml
├── src/
│   └── package/
└── tests/
```

A estrutura deve representar as responsabilidades reais do código.

Não crie diretórios ou camadas apenas para seguir templates.

---

# 4. Packages

Não adicione `__init__.py` automaticamente.

Namespace packages são suportados pelo Python moderno.

Utilize `__init__.py` somente quando existir uma necessidade concreta, como:

- comportamento de inicialização do pacote;
- definição explícita de uma API pública;
- requisito de packaging;
- requisito de tooling;
- necessidade de regular package.

Um `__init__.py` vazio não deve ser criado apenas por tradição.

Não coloque lógica de aplicação em `__init__.py`.

Quando utilizado, o arquivo deve possuir uma responsabilidade clara.

---

# 5. Entrypoints

`main.py` deve ser utilizado como padrão para o entrypoint de componentes executáveis.

A convenção é:

```text
main.py
→ entrypoint do componente executável
```

Cada feature do control loop (um tipo de recurso, com Receiver, Manager, Publisher, Observer, Reconciler e Executor) é um projeto Python, com o `main.py` de cada papel, um `pyproject.toml` e um lockfile. O layout (`features/<módulo>/<tipo>/`), o pacote (`<módulo>_<tipo>`, com um subpacote por papel e o `common/`) e a proibição de um papel importar outro estão em `.decisions/0063-um-componente-por-feature-com-um-entrypoint-por-papel.md`; não os repita aqui.

Toda feature tem o seu documento de fluxo de dados (`features/<módulo>/<tipo>/docs/<MÓDULO>-<TIPO>-DATA-FLOW.md`); nome, estrutura e manutenção estão em `.decisions/0024-data-flow-por-feature.md`: atualize-o ao mudar mensagem, rota, schema, migração ou privilégio, e não repita a estrutura aqui.

Evite nomes redundantes como:

```text
api/api.py
manager/manager.py
```

quando `main.py` comunicar claramente a responsabilidade.

O entrypoint deve ser pequeno e responsável principalmente pela inicialização do componente.

A lógica de negócio não deve ser concentrada em `main.py`.

## 5.1 Estrutura interna dos componentes

A estrutura interna dos componentes (`domain/` puro e sem I/O, orquestração em `handlers/` ou `engine/`, adaptadores em `store/`, `provider/`, `transport/`, `http/` e `outbox/`, e `main.py`) e a regra de dependência (`main → orquestração → domain`, o `domain` sem importar adaptador) estão em `.decisions/0017-estrutura-interna-dos-componentes-e-relay-no-manager.md`, e a divisão `provider/` (conexão) e `drivers/` (um por sub-recurso, espelhados entre Executor e Observer) em `.decisions/0073-drivers-espelhados-no-executor-e-no-observer.md`; não as repita aqui. Em Python:

- o `domain/` não importa `psycopg`, `nats`, `httpx`, `fastapi` nem módulos de adaptadores; cada projeto tem um teste que falha se isso acontecer;
- as portas (contratos entre orquestração e adaptadores) são `Protocol` definidos junto de quem as usa;
- cada componente é um processo e expõe **um** script em `[project.scripts]` (`<módulo>-<tipo>-<papel>`); um comportamento que exija privilégio diferente é outro papel, e não um modo (decisão 0019).

---

# 6. Typing

Type hints devem ser utilizados de forma consistente.

Prefira os recursos modernos de typing disponíveis no Python 3.14.

Utilize typing para representar:

- Contratos
- Interfaces
- Parâmetros
- Retornos
- Estruturas de dados
- Dependências entre componentes

Evite tipos excessivamente complexos quando uma definição simples for suficiente.

Não utilize `Any` indiscriminadamente para contornar problemas de tipagem.

Quando um tipo realmente precisar ser dinâmico, isso deve ser explícito.

---

# 7. Pyright

**Pyright** é o padrão para type checking estático do projeto.

O código Python deve passar pelo Pyright antes de ser considerado concluído.

Execução:

```text
uv run pyright
```

Problemas de tipagem não devem ser ignorados para permitir a execução do código.

Suppressions do Pyright devem ser usadas somente quando houver uma justificativa concreta.

Quando uma exceção for necessária, mantenha-a localizada e explícita.

---

# 8. Ruff

**Ruff** é a ferramenta padrão para linting e formatação do código Python.

Utilize Ruff para:

- Lint
- Formatação
- Validações estáticas suportadas
- Padronização do código

Validação:

```text
uv run ruff check .
uv run ruff format --check .
```

Formatação:

```text
uv run ruff format .
```

Ruff deve ser a referência principal para linting e formatação Python.

Não adicione ferramentas adicionais de lint ou formatação sem necessidade concreta.

---

# 9. pytest

**pytest** é o framework padrão para testes Python.

Os testes devem ser organizados conforme as responsabilidades do componente.

Quando aplicável:

```text
tests/
├── unit/
└── integration/
```

Testes unitários devem permanecer rápidos e isolados.

Testes de integração devem validar a interação real entre componentes ou dependências relevantes.

Utilize fixtures quando elas melhorarem clareza e manutenção.

Evite fixtures excessivamente implícitas ou difíceis de compreender.

---

# 10. Coverage

A cobertura de testes deve ser medida durante a execução dos testes.

Utilize `pytest-cov` ou mecanismo equivalente integrado ao pytest.

Execução padrão:

```text
uv run pytest --cov
```

Relatório detalhado:

```text
uv run pytest --cov --cov-report=term-missing
```

Coverage deve ser utilizado para identificar partes relevantes do código que não possuem testes.

Não escreva testes artificiais apenas para aumentar percentual de cobertura.

Coverage não substitui testes de comportamento adequados.

---

# 11. Quality Gate Python

Para alterações Python relevantes, executar:

```text
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov
```

A sequência conceitual é:

```text
Ruff
  ↓
Pyright
  ↓
pytest
  ↓
coverage
```

Verificações adicionais podem ser utilizadas quando houver necessidade específica do componente.

A configuração dessas ferramentas deve permanecer centralizada no `pyproject.toml` sempre que possível.

---

# 12. pyproject.toml

O `pyproject.toml` é a principal fonte de configuração do projeto Python.

Quando aplicável, centralize nele:

- Metadados do projeto
- Dependências
- Scripts
- Configuração do Ruff
- Configuração do Pyright
- Configuração do pytest
- Configuração de coverage
- Configuração de packaging

Evite espalhar configurações equivalentes por múltiplos arquivos.

Quando uma ferramenta exigir configuração própria por uma razão concreta, siga sua convenção.

---

# 13. Dependências

Novas dependências devem ser adicionadas utilizando uv.

Diferencie:

- Dependências de runtime
- Dependências de desenvolvimento
- Dependências opcionais

Antes de adicionar uma dependência, avalie:

- Necessidade real
- Funcionalidade oferecida
- Alternativas existentes
- Impacto no packaging
- Segurança
- Manutenção
- Complexidade

Prefira a biblioteca padrão quando ela atender adequadamente ao problema.

---

# 14. Programação Assíncrona

Utilize `asyncio` e APIs assíncronas quando o problema envolver operações de I/O concorrentes.

Não introduza programação assíncrona apenas por preferência.

Mantenha explícito:

- O que é síncrono.
- O que é assíncrono.
- Onde existe concorrência.
- Onde existe espera de I/O.
- Onde existe paralelismo.

Evite misturar diferentes modelos de concorrência sem necessidade.

---

# 15. Estruturas e Recursos da Linguagem

Utilize recursos modernos do Python quando forem apropriados ao problema.

Entre eles:

- Type hints modernos
- `dataclass`
- `Enum`
- `Protocol`
- Pattern matching
- Context managers
- Generators
- Iterators
- Async/await
- Structural typing

Não utilize um recurso apenas porque ele existe.

A escolha deve melhorar a clareza do código ou representar corretamente o domínio.

---

# 16. Classes e Funções

Prefira funções quando elas forem suficientes.

Utilize classes quando existir estado, comportamento ou abstração que justifique sua existência.

Evite classes utilizadas apenas para agrupar funções sem necessidade.

Evite hierarquias profundas de herança.

Prefira composição quando ela produzir uma estrutura mais simples.

---

# 17. Exceções

Utilize exceções específicas para representar condições excepcionais.

Prefira:

```python
except SpecificError:
    ...
```

em vez de:

```python
except Exception:
    ...
```

quando isso puder ocultar erros inesperados.

Não utilize exceções como mecanismo normal de controle de fluxo quando uma representação explícita for mais adequada.

Exceções devem preservar contexto suficiente para diagnóstico.

---

# 18. Logging

Utilize o mecanismo de logging definido pelo projeto.

Logs Python devem ser estruturados de acordo com a necessidade do componente.

Padrão dos componentes: JSON, uma linha por evento; mensagem estática em inglês e todo dado dinâmico no `extra` (chaves em inglês, `snake_case`), nunca interpolado na mensagem; `INFO` para marcos de negócio (sem `subject`, caminhos ou identificadores técnicos além do `resource_id`), `WARNING` para anomalia recuperável, `ERROR` para falha de uma operação e `CRITICAL` para falha que compromete o processo. Mensagens de exceção não entram no log (podem conter valores de colunas): registra-se só o tipo e o local.

Não inclua em logs:

- Secrets
- Credenciais
- Tokens
- Chaves privadas
- Dados sensíveis desnecessários

O logging deve fornecer contexto operacional sem gerar ruído desnecessário.

---

# 19. Configuration

Configuração da aplicação deve ser separada do código.

Diferencie explicitamente:

```text
configuration
secrets
runtime state
application state
```

Valores específicos de ambiente não devem ser incorporados diretamente ao código.

A estratégia específica de configuração deve ser definida pelo componente ou pela infraestrutura responsável.

---

# 20. Packaging

Projetos e pacotes Python devem possuir metadados claros no `pyproject.toml`.

O build backend padrão é `uv_build`.

Quando apropriado, aplicações executáveis devem utilizar entry points definidos no packaging Python.

Exemplo:

```toml
[project.scripts]
sk = "sk.main:main"
```

O mecanismo de execução deve ser definido pelo packaging do projeto, e não depender da execução manual de arquivos Python.

## 20.1 CLI

O CLI `sk` usa **Typer** para os comandos e **pydantic-settings** para a configuração, com precedência parâmetro → variável de ambiente (`SK_<SEÇÃO>_<CAMPO>`) → arquivo `config.toml` → default. A decisão e as regras estão em `.decisions/0008-cli-typer-pydantic-e-precedencia-de-configuracao.md`; não as repita aqui.

---

# 21. Testes e Estrutura do Componente

Cada feature tem os seus testes (`unit`, `contract` e `integration`), no próprio projeto, em `tests/<papel>/` e `tests/common/`. Os testes e2e do contrato (black-box, pela rede) ficam em `features/<módulo>/<tipo>/tests/e2e`, como um projeto de testes, e não importam o código da feature (decisões 0015, 0017 e 0063). Eles não são um componente.

Quando um componente possuir múltiplos entrypoints, os testes podem acompanhar essa separação:

```text
tests/
├── unit/
│   ├── api/
│   └── worker/
└── integration/
    ├── api/
    └── worker/
```

Essa estrutura deve existir somente quando representar uma separação real de responsabilidades.

Não crie diretórios de testes apenas para completar um padrão.

---

# 22. Verificação de Desenvolvimento

Durante o desenvolvimento, prefira executar as ferramentas por meio de uv.

Exemplos:

```text
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest --cov
```

Para validação sem alterar arquivos:

```text
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov
```

Para gerar os artefatos de distribuição:

```text
uv build
```

---

# 23. Código orientado a contratos e ao control loop

As regras de contrato, mensageria e persistência pertencem aos documentos de `docs/`; este arquivo define apenas como o código Python as respeita:

- **Modelos derivados de schemas** são arquivos gerados: altere o schema, regenere e confira a diferença na CI (`docs/data/SCHEMA.md`). Não edite o modelo gerado.
- **Validação nas fronteiras:** validação estrita na entrada de clientes externos e na publicação, e tolerante no consumo interno, conforme `docs/data/SCHEMA.md`.
- **Tempo:** use instantes com timezone explícito (UTC). Não compare relógios de componentes diferentes para ordenar eventos (`docs/messaging/MESSAGING.md`).
- **Idempotência:** todo consumidor trata a mesma mensagem mais de uma vez sem efeito nocivo. Confirme a mensagem apenas após o processamento durável.
- **Logs e erros:** nunca registre campos `confidential`, segredos ou referências resolvidas (`docs/data/SCHEMA.md`). Mensagens de erro identificam a regra violada, e não repetem valores sensíveis.
- **Testes:** além de unidade e integração, cubra testes de contrato, de idempotência do consumidor (mensagem duplicada) e de concorrência otimista.
- **Sem biblioteca interna comum:** uma feature não importa outra nem uma biblioteca interna compartilhada. O que é idêntico entre features vem do template (`templates/feature`, decisão 0064); modelos são gerados dos schemas em cada feature, e o contrato comum é verificado pelos testes e2e (decisões 0015 e 0017).
- **Clientes de mensageria e de banco:** a escolha das bibliotecas segue a seção de dependências e deve ser registrada como decisão em `.decisions/`. Não escolha por conveniência.

---

# 24. Evolução das Convenções Python

Este arquivo deve concentrar as convenções específicas de Python adotadas pelo projeto.

Quando surgir uma nova necessidade:

1. Verifique se a convenção existente atende ao requisito.
2. Prefira a menor extensão necessária.
3. Reutilize ferramentas já adotadas quando possível.
4. Evite introduzir uma nova ferramenta para resolver um problema já coberto.
5. Atualize esta fonte da verdade quando uma nova convenção Python for oficialmente adotada.