# 0012 — Formato dos contratos: JSON Schema 2020-12

- **Data:** 2026-10-09
- **Status:** Aceita

## Contexto

`docs/SCHEMA.md` §5.3 deixa o formato dos contratos em aberto e exige registrá-lo em `.decisions/`. O `schemas/` está vazio, e o primeiro recurso (Organization) precisa dos contratos antes da implementação (`SCHEMA.md` §25).

## Decisão

- **Formato:** JSON Schema 2020-12, um arquivo por contrato com o nome `<contrato>.v<MAJOR>.schema.json` (`SCHEMA.md` §5.3).
- **Estrutura:**
  - `schemas/common/` guarda as definições comuns, como `resourceId` e o envelope;
  - cada recurso fica em `schemas/<módulo>/<tipo>/`, por exemplo `schemas/core/organization/`;
  - as referências entre arquivos são só locais, por `$ref` relativo (`SCHEMA.md`).
- **Anotações de campo** (`SCHEMA.md` §9.1), expressas como palavras-chave de extensão com o prefixo `x-`:
  - `x-writer`, `x-mutability`, `x-managed`, `x-normalization`, `x-providerDefault`, `x-sensitivity` e `x-enumPolicy`, no campo;
  - os parâmetros do recurso (§9.2), em `x-resourceParameters` na raiz do contrato `desired`.
- **`title`** de cada contrato e de cada objeto ou enum aninhado é o nome técnico em PascalCase e em inglês (`OrganizationDesiredData`, `MessageEnvelope`), conforme `AGENTS.md` §16.1. Ele vira o nome da classe gerada. A explicação em pt-BR fica em `description`.
- **Índice por módulo:** `schemas/<módulo>.index.json` lista (`anyOf` de `$ref`) os contratos que o módulo consome e é a entrada do gerador. Ele não é um contrato. Fica na raiz de `schemas/` para que todas as referências estejam sob o diretório base do gerador, que roda com a busca remota de `$ref` bloqueada (`allow-remote-refs = false`). Um teste garante que todo contrato de `common/` e do módulo esteja listado.
- **Artefatos derivados:** os modelos Pydantic v2 são gerados pelo `datamodel-code-generator`, com configuração no `pyproject.toml` do módulo, num único arquivo versionado (`features/<módulo>/src/<módulo>/contracts/generated.py`). O teste de contrato regera os modelos e falha se houver diferença (`SCHEMA.md` §22). Os modelos gerados nunca são editados à mão (`python.md` §23).
- **Datas e durações:** strings com `format` `date-time` ou `duration` não declaram `maxLength`. O próprio formato limita o tamanho, e os modelos as convertem em `datetime` e `timedelta`, aos quais `maxLength` não se aplica.

## Justificativa

- JSON Schema é o formato nativo dos payloads JSON das mensagens e da API, e o FastAPI e o Pydantic o usam diretamente.
- As palavras-chave `x-` preservam a validação padrão: validadores ignoram as anotações desconhecidas.

## Consequências

- O gerador e o `jsonschema` (testes de contrato) entram como dependências de desenvolvimento do módulo `core`.
- O gerador formata a saída com o `ruff format` usando a configuração mais próxima do arquivo de saída; por isso a verificação regera dentro do próprio projeto.
- Formatos binários (Protobuf, Avro) ficam fora enquanto não houver requisito.
