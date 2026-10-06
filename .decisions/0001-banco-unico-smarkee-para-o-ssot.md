# 0001 — Banco único `smarkee` para o SSOT

- **Data:** 2026-10-06
- **Status:** Aceita

## Contexto

O SSOT será implementado em PostgreSQL (`docs/POSTGRESQL.md`), com um schema por módulo e tabelas por tipo de recurso. No ambiente de desenvolvimento, o mesmo servidor PostgreSQL também hospeda os bancos do gateway (`kong`) e do provedor de identidade (`zitadel`). Era preciso decidir quantos bancos o SSOT usa, como ele se chama e com quem divide o servidor.

## Decisão

- O SSOT usa **um único banco**, `smarkee`, para todos os módulos. O isolamento entre módulos e tipos é feito por schema, por tabela, por view e por `GRANT`.
- O banco pertence ao papel `smarkee_owner`, que não é superusuário e é usado somente por migração e recuperação. Serviços de runtime usam papéis próprios.
- `PUBLIC` não possui `CONNECT` nem `TEMPORARY` no banco, nem privilégios no schema `public`.
- O SSOT não compartilha banco com componentes de terceiros. No desenvolvimento, ele divide o servidor com `kong` e `zitadel`; fora do ambiente local, usa um **cluster próprio**.

## Justificativa

- Um banco por módulo multiplicaria conexões, backups, procedimentos de recuperação e migrações sem acrescentar isolamento que os privilégios já não garantam.
- O SSOT tem objetivos de recuperação e um procedimento de recuperação próprios (`docs/SSOT.md`). Restaurar o SSOT a um ponto no tempo não pode restaurar o gateway ou o provedor de identidade junto, o que exige separação de cluster fora do desenvolvimento.
- O proprietário não superusuário limita o impacto de uma credencial de migração exposta.

## Consequências

- `infrastructure/dev/database/initdb/smarkee.sql` cria o proprietário e o banco no desenvolvimento.
- A infraestrutura de cada ambiente deve prover um cluster dedicado ao SSOT fora do desenvolvimento.
- Cada papel de serviço recebe `CONNECT` explicitamente nas migrações do seu tipo.
