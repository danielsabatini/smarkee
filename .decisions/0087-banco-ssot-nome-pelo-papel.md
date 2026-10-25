# 0087 — Banco e proprietário do SSOT se chamam `ssot`

- **Data:** 2026-10-25
- **Status:** Aceita. Substitui a decisão 0001 quanto ao **nome** do banco e do proprietário. O restante da 0001 continua válido.

## Contexto

O SSOT usava o banco `smarkee` e o proprietário `smarkee`, o nome da marca. Os outros bancos já levam o papel que cumprem: `identity` (provedor de identidade) e `platform` (plano de dados, decisão 0086). O §15.1 do `AGENTS.md` manda nomear pelo papel, e `smarkee` não diz se o banco é o SSOT ou o plano de dados.

## Decisão

- O banco do SSOT passa a se chamar `ssot`, e o proprietário não superusuário, `ssot`. Nada mais muda no desenho da 0001.
- O bootstrap é `infrastructure/dev/database/bootstrap/ssot.sql` (era `smarkee.sql`).
- O código de produção não conhecia o nome: `DatabaseSettings.name` vem do `config.toml`. Mudaram configuração (`config.toml`, `.env.example`, `compose.yaml` das migrações), as migrações (`GRANT CONNECT ON DATABASE`), os testes, o bootstrap, a telemetria e as ferramentas de dev.
- O rótulo de telemetria `db.namespace` do SSOT passa de `smarkee|<schema>` a `ssot|<schema>`. É o nome do banco, como em `identity|...` e `platform|...`. Não confundir com `service.namespace = smarkee`, que é o produto e não muda.
- O usuário NATS `smarkee`, o domínio `*.smarkee.internal`, o label `smarkee.layer`, as imagens `smarkee-*` e o prefixo `SMARKEE_` das variáveis de infraestrutura (decisão 0069) são da marca ou de outro papel e **não mudam**.

## Migração

- **Ambiente existente:** com a stack das features parada, `ALTER DATABASE smarkee RENAME TO ssot` e `ALTER ROLE smarkee RENAME TO ssot` (o PostgreSQL só renomeia banco sem conexões), `ALTER ROLE ssot PASSWORD 'ssot'`, reaplicar `telemetry.sql` e subir a stack. `GRANT`s, dono dos objetos e dados acompanham o rename: não há migração de dados.
- **Ambiente novo:** o `initdb.d` já cria `ssot`.
- **`.env` locais não versionados:** a variável `<FEATURE>_*_DATABASE_NAME`, se estiver definida, deve passar a `ssot`.
- **Backups anteriores:** o dump se chamava `smarkee.dump` e o manifesto lista `smarkee`; a ferramenta de backup só aceita os bancos atuais, então os **backups anteriores a esta decisão não são restauráveis por ela**. Restaurar um deles exige `pg_restore --create` manual e o rename acima.
- Conexões salvas em clientes externos (por exemplo o DBeaver) apontam para o nome antigo.

## Compatibilidade (§10, §31)

`name` do banco é contrato de configuração. Não se aceitam os dois nomes: seria complexidade sem necessidade em dev. As migrações `0001` das features foram editadas no lugar (são idempotentes e reaplicadas a cada `up`).

## Melhorias avaliadas para uma próxima troca

O nome ainda é literal em 21 `config.toml`, 21 linhas de `compose.yaml` (`PGDATABASE`, `PGUSER`, `PGPASSWORD`), 7 migrações (`GRANT CONNECT ON DATABASE`), ~36 pontos de teste, no template e no bootstrap. Candidatas, **não implementadas** nesta decisão:

1. Migrações: `SELECT current_database() AS ssot_database \gset` e `GRANT CONNECT ON DATABASE :"ssot_database"`, para deixar de depender do nome.
2. Testes: ler o nome de uma variável `<ESCOPO>_TEST_DATABASE_NAME` (hoje só `HOST` e `PORT` são variáveis).
3. `compose.yaml` das migrações: `PGDATABASE`/`PGUSER`/`PGPASSWORD` de variáveis com padrão `ssot`.

O `config.toml` por componente continua literal por desenho (a configuração é o lugar do nome).
