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
- **Artefatos derivados:** os modelos Pydantic v2 são gerados pelo `datamodel-code-generator` e versionados. A verificação regera os modelos e falha se houver diferença (`SCHEMA.md` §22). Os modelos gerados nunca são editados à mão (`python.md` §23).

## Justificativa

- JSON Schema é o formato nativo dos payloads JSON das mensagens e da API, e o FastAPI e o Pydantic o usam diretamente.
- As palavras-chave `x-` preservam a validação padrão: validadores ignoram as anotações desconhecidas.

## Consequências

- O gerador entra como dependência de desenvolvimento do serviço `core`.
- Formatos binários (Protobuf, Avro) ficam fora enquanto não houver requisito.
