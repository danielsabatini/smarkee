# 0089 — Sementes do catálogo com `resourceId` UUIDv7 e `roleType` na Role

- **Data:** 2026-10-26
- **Status:** Aceita. Corrige as sementes das decisões `0083` e `0088` e complementa `docs/SCHEMA.md` §8.1.

## Contexto

O `resourceId` é opaco e independente do nome (`docs/SCHEMA.md` §8.1), e todo recurso criado pela API recebe um UUIDv7. As sementes de `ipm.permission` e `ipm.role` usavam IDs legíveis (`perm-ipm-user-create`, `role-ipm-user-admin`), o que misturava semântica na identidade e deixava o catálogo fora do padrão dos demais recursos. As sementes de `ipm.group*` existiam só no banco de dev, sem migração.

Além disso, nada distinguia uma Role do catálogo da plataforma de uma Role criada por pedido.

## Decisão

- As sementes de `ipm.permission` e `ipm.role` passam a ter **UUIDv7 fixos** nas migrações `0001`. O valor é fixo para o `INSERT` continuar idempotente e igual em todos os ambientes.
- As migrações `0002` trocam os IDs legados pelos UUIDv7 em ambientes existentes (tabelas do tipo, operações, resultados de ação e outbox). Nas Roles do `platform`, a chave estrangeira de `ipm.role_permission` passa a `ON UPDATE CASCADE`. Em volume novo as `0002` não alteram nada.
- Mensagens `desired` ainda não publicadas com o ID antigo são descartadas, e cada recurso renomeado ganha um `desired` novo com `messageId` determinístico. As já publicadas ficam como histórico.
- As sementes `ipm.group*` entram nas migrações `0001`.
- A Role ganha `roleType` (`predefined` | `custom`), `x-writer = server` e imutável. O bootstrap grava `predefined`. O Receiver não aceita o campo no `POST`, e o Manager grava `custom` nas Roles criadas por pedido. Ausente em dados antigos, vale `custom`.
- `roleType` está em `desired` e na visão do recurso. Não está em `observed`: o banco `platform` não o guarda, e o Observer não o lê.

## Consequências

- Contrato aditivo (campo novo, com padrão para dados antigos). O `resourceId` das sementes muda, e quem guardava o ID antigo precisa ler de novo pelo `name`. Os catálogos em memória de `ipm/user`, `ipm/group` e `ipm/organization` indexam por `name` e convergem sozinhos.
- Fica em aberto quem pode criar Roles `custom`: hoje só `ipm.role.admin`. Abri-las a usuários das Organizations exige escopo por `organizationId` no SSOT e no Receiver, e será decidido à parte.
