-- Proprietário e banco do SSOT (apenas desenvolvimento local; credenciais triviais).
-- Conforme docs/data/POSTGRESQL.md: banco único `ssot`, proprietário `ssot` (não superusuário),
-- usado somente por migração e recuperação. Os papéis de serviço são criados por `core.sql` e `ipm.sql`
-- (um arquivo por módulo), e os privilégios, pela migração de cada tipo.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ssot') THEN
    CREATE ROLE ssot LOGIN;
  END IF;
END
$$;

ALTER ROLE ssot PASSWORD 'ssot';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
-- Provedor de localidade builtin (C.UTF-8): ordenação por ponto de código, igual em qualquer
-- sistema operacional e biblioteca C (a imagem alpine/musl e um servidor glibc ordenariam diferente).
SELECT 'CREATE DATABASE ssot OWNER ssot ENCODING ''UTF8'' LOCALE_PROVIDER builtin BUILTIN_LOCALE ''C.UTF-8'' LOCALE ''C.UTF-8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ssot') \gexec

ALTER DATABASE ssot OWNER TO ssot;

-- Por padrão, PUBLIC possui CONNECT e TEMPORARY em todo banco; cada serviço recebe CONNECT explicitamente.
REVOKE ALL ON DATABASE ssot FROM PUBLIC;

\connect ssot

-- Por padrão, PUBLIC possui USAGE no schema public; o SSOT usa um schema por módulo.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
