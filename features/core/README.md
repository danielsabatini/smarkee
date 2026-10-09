# core — recursos da plataforma

Módulo `core` da plataforma: recursos dos quais os demais módulos dependem, começando pela Organization (decisões 0009 a 0011). Requer Python 3.14 e [uv](https://docs.astral.sh/uv/).

Estado atual: contratos e modelos gerados (Fase 1). O serviço (API, Manager, Reconciler, Executor, Observer) ainda não foi implementado.

## Contratos

Os contratos ficam em `schemas/` (JSON Schema 2020-12, decisão 0012):

- `schemas/common/`: envelope, condition, action, completed, failed, updated, Operation e as respostas comuns da API;
- `schemas/core/organization/`: desired, observed, requested (create, update, delete), pedidos da API e a visão consolidada;
- `schemas/core.index.json`: lista dos contratos usados pelo módulo, entrada do gerador.

Os modelos Pydantic ficam em `src/core/contracts/generated.py`, gerados a partir do índice. **Não edite esse arquivo**: altere o schema e regere.

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
- índice completo e modelos gerados idênticos à regeneração.
