# core — recursos da plataforma

Módulo `core` da plataforma: recursos dos quais os demais módulos dependem, começando pela Organization (decisões 0009 a 0011). Requer Python 3.14 e [uv](https://docs.astral.sh/uv/).

Estado atual: contratos, modelos gerados e migrações do SSOT. O serviço (API, Manager, Reconciler, Executor, Observer) ainda não foi implementado.

## Contratos

Os contratos ficam em `schemas/` (JSON Schema 2020-12, decisão 0012):

- `schemas/common/`: envelope, condition, action, completed, failed, updated, Operation e as respostas comuns da API;
- `schemas/core/organization/`: desired, observed, requested (create, update, delete), pedidos da API e a visão consolidada. Sem dados pessoais; o dono é `ownerUserId`;
- `schemas/core/user/`: desired, observed, requested (create, delete), pedido de auto-cadastro e visão consolidada. Sem senha (decisão 0014); nome e e-mail são `confidential`, e o `desired` com `lifecycle = absent` não os carrega;
- `schemas/core.index.json`: lista dos contratos usados pelo módulo, entrada do gerador.

Os modelos Pydantic ficam em `src/core/contracts/generated.py`, gerados a partir do índice. **Não edite esse arquivo**: altere o schema e regere.

Grafia (`docs/SCHEMA.md` §8.3): os atributos Python são `snake_case` (`observed_generation`) e o JSON é camelCase (`observedGeneration`), por alias. A conversão fica numa só classe base, `core.contracts.base.ContractModel`: só o nome do contrato é aceito na entrada (a grafia Python é rejeitada), `model_dump()` e `model_dump_json()` já saem com o nome do contrato, e propriedade desconhecida é rejeitada. Para construir um modelo em código, valide um dicionário com os nomes do contrato (`Modelo.model_validate({...})`).

O `if/then/else` de um schema (por exemplo, o `desired` do User sem dados pessoais quando `absent`) **não** vira validação no modelo Pydantic: o modelo tem os campos opcionais. A regra é conferida pelo Manager e pelos testes de contrato.

```bash
uv sync
uv run datamodel-codegen      # regera src/core/contracts/generated.py (configuração no pyproject.toml)
```

## Qualidade

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov --cov-report=term-missing
```

Os testes de contrato (`tests/contract`) verificam, para `common/` e `core/`:

- schema válido, versão coerente com o nome do arquivo e referências somente locais;
- limites em toda string e array, objetos fechados, `x-sensitivity` e `x-writer` em todo campo e `x-enumPolicy` em todo enum;
- exemplos válidos, rejeição de campo desconhecido e de campos atribuídos pelo servidor enviados pelo cliente;
- índice completo e modelos gerados idênticos à regeneração;
- nomes: atributos em snake_case, saída camelCase e entrada em snake_case rejeitada;
- contratos da Organization sem dados pessoais e contratos do User sem campo de senha.
