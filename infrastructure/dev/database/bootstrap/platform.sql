-- Proprietário e banco `platform` (apenas desenvolvimento local; credenciais triviais).
-- Plano de dados multi-tenant das soluções próprias da Smarkee (Roles, usuários, grupos...), SEPARADO do
-- SSOT (`smarkee`) e do Zitadel (`identity`). Hoje roda no mesmo servidor; aponta-se para outro servidor
-- só por configuração (`host`, `port`, `name`) dos Executors e Observers.
-- Segue o padrão de `smarkee.sql`: proprietário próprio (não superusuário), usado somente por migração e
-- recuperação. Os papéis de runtime (`<módulo>_<tipo>_executor` e `_observer`) são criados por
-- `<módulo>.sql`; os privilégios, pela migração `migrations/platform/` de cada tipo.
-- Nenhum papel do SSOT recebe CONNECT neste banco.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'platform') THEN
    CREATE ROLE platform LOGIN;
  END IF;
END
$$;

ALTER ROLE platform PASSWORD 'platform';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
-- Mesmo provedor de localidade do SSOT (builtin C.UTF-8): ordenação igual em qualquer sistema.
SELECT 'CREATE DATABASE platform OWNER platform ENCODING ''UTF8'' LOCALE_PROVIDER builtin BUILTIN_LOCALE ''C.UTF-8'' LOCALE ''C.UTF-8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'platform') \gexec

ALTER DATABASE platform OWNER TO platform;

-- Por padrão, PUBLIC possui CONNECT e TEMPORARY em todo banco; cada papel recebe CONNECT explicitamente.
REVOKE ALL ON DATABASE platform FROM PUBLIC;

\connect platform

-- Por padrão, PUBLIC possui USAGE no schema public; o banco usa um schema por módulo.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
