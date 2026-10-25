# 0086 — Banco `platform`: plano de dados multi-tenant das soluções próprias

- **Data:** 2026-10-25
- **Status:** Aceita. Revisa os trechos das decisões `0073` e `0083` que mantinham o estado de `ipm.role` em arquivos no disco do Executor e do Observer.
- **Origem:** O estado de `ipm.role` em `<stateDir>/<resourceId>.json` (volume `ipm-role-state`) não escala para os próximos recursos (`ipm.user`, `ipm.group`, e possivelmente `sum` e `bsm`), não é consultável nem transacional e não é multi-tenant.

## Contexto

O Executor aplica o estado pretendido no sistema externo e o Observer o lê de volta (loop de reconciliação, modelo do Kubernetes: `desired` no SSOT, estado real no sistema controlado). Para `ipm.role`, o "sistema externo" era um arquivo JSON por Role, escrito atomicamente. Isso serviu como primeiro degrau (§2.2), mas as soluções próprias da Smarkee (Roles, usuários, grupos e suas relações) precisam de um plano de dados relacional, multi-tenant e consultável.

O SSOT (`smarkee`) guarda a intenção e o ciclo de vida; o Zitadel (`identity`) guarda identidade. Misturar o plano de dados em qualquer um dos dois confundiria responsabilidades (§26) e impediria movê-lo para outro servidor.

## Decisão

1. Um banco PostgreSQL novo, **`platform`**, separado do SSOT e do Zitadel. Hoje no mesmo servidor; apontar para outro servidor ou cluster exige só configuração (`host`, `port`, `name`) do Executor e do Observer.
2. **Multi-tenant** por `organization_id`, com o mesmo identificador de Organization do Zitadel. As Roles globais predefinidas ficam na organização `core`.
3. **Um schema por módulo** (`ipm`), sem chave estrangeira entre schemas de módulos diferentes. Modelo normalizado, não `jsonb`: `ipm.role` e `ipm.role_permission` (`ON DELETE CASCADE`), com `UNIQUE (organization_id, name)` e `CHECK`s que repetem os padrões dos JSON Schemas. Tabelas previstas: `ipm.group`, `ipm.group_role`, `ipm.group_member`, `ipm.user_role`.
4. **Só o Executor escreve; o Observer só lê.** Papéis `ipm_role_executor` (leitura e escrita) e `ipm_role_observer` (`SELECT`), cada um com `_login`, criados em `infrastructure/dev/database/bootstrap/ipm.sql`. Nenhum papel do SSOT recebe `CONNECT` em `platform`. Executor e Observer continuam sem acesso ao SSOT.
5. **Migrações por feature:** `features/ipm/role/migrations/platform/`, aplicadas por `ipm-role-migrate` como o dono `platform`. A migração do SSOT permanece em `migrations/`.
6. **Erros:** no Executor, violação de integridade ou de dado vira `Rejected` (sem nova tentativa); os demais erros do driver viram `ExternalError` (com nova tentativa), sem repassar a mensagem do driver. No Observer, qualquer erro de banco vira `unknown`, nunca `absent`.
7. `bsm/account` continua em disco por ora (decisão `0082`); migrá-lo é eventual e fica fora desta decisão.

## Referência de mercado e divergência (§2.7)

O modelo é o do Kubernetes: o controlador reconcilia o estado desejado com o estado real de um sistema externo. Diverge ao usar PostgreSQL como esse sistema externo, o que não é uma divergência do modelo, só do alvo.

## Justificativa

- **Segurança:** menor privilégio por papel; isolamento do SSOT; `CHECK`s como defesa em profundidade.
- **Simplicidade:** reaproveita o PostgreSQL e o `open_pool` já existentes; nenhum serviço novo.
- **Robustez:** transação por gravação (Role e permissões juntas); restrições no banco.
- **Resiliência:** escrita idempotente (upsert; delete idempotente); falha de banco nunca é confundida com ausência.
- **Caminho aditivo (§2.6):** `ipm.user`, `ipm.group` e demais módulos acrescentam tabelas e papéis ao mesmo banco, sem trocar o contrato.

## Consequências

- Novas senhas `IPM_ROLE_EXECUTOR_DATABASE_PASSWORD` e `IPM_ROLE_OBSERVER_DATABASE_PASSWORD`; seção `database` no `config.toml` do Executor e do Observer; volume `ipm-role-state` deixa de ser usado (o seed recria as Roles predefinidas; o volume antigo não é migrado nem removido automaticamente).
- O backup de dev (`scripts/dev/backup`) inclui o banco `platform`; o telemetry-agent o coleta (`GRANT CONNECT` ao papel `telemetry`).
- Em ambiente existente, `platform.sql`, `ipm.sql` e `telemetry.sql` são aplicados manualmente como `postgres` (o `initdb.d` só roda em volume novo).

## Lacunas declaradas de dev (§2.5)

| Lacuna | Condição de saída (antes do stg) |
|---|---|
| Senhas triviais dos papéis `platform`, `ipm_role_executor_login` e `ipm_role_observer_login` | Cofre de segredos |
| Mesmo servidor que o SSOT, sem réplica nem backup próprio além do script de dev | Servidor ou cluster dedicado, com backup e réplica |
| O banco padrão `postgres` mantém `CONNECT` público no cluster | Revogar o `CONNECT` público nos bancos de sistema |
