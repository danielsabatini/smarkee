# 0004 — Leitura da API por views versionadas

- **Data:** 2026-10-06
- **Status:** Aceita

## Contexto

A API lia diretamente as tabelas do SSOT, com `SELECT` por coluna. Isso fazia da estrutura de armazenamento um contrato implícito com a API, o que contraria `docs/SCHEMA.md`: a persistência é uma representação mapeada do contrato, e não o contrato. Também acoplava as migrações da tabela ao código da API.

## Decisão

- A API lê somente as views `<tipo>_v<MAJOR>` e `<tipo>_operation_v<MAJOR>`, geradas do modelo junto com as tabelas.
- O `MAJOR` da view acompanha o `MAJOR` do contrato da visão consolidada do recurso.
- O papel da API recebe `SELECT` apenas nas views, e nenhum privilégio nas tabelas.

## Justificativa

- A view é a interface de leitura explícita e versionada. Uma migração da tabela (expandir → migrar → contrair) não afeta a API enquanto o contrato de leitura não mudar.
- A seleção de colunas expostas fica em um único lugar, a definição da view, em vez de espalhada em `GRANT` por coluna.
- Não há dependência nova: views simples são recurso nativo do PostgreSQL.

## Consequências

- As views executam com os privilégios do proprietário (padrão do PostgreSQL). Se um tipo adotar Row-Level Security, as views desse tipo passam a usar `security_invoker`.
- Uma mudança incompatível do contrato de leitura cria a view do novo `MAJOR`, que coexiste com a anterior durante a janela de coexistência.
