-- Proprietário e banco do SSOT (apenas desenvolvimento local; credenciais triviais).
-- Conforme docs/POSTGRESQL.md: banco único `smarkee`, proprietário `smarkee` (não superusuário),
-- usado somente por migração e recuperação. Papéis de serviço são criados pelas migrações de cada tipo.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'smarkee') THEN
    CREATE ROLE smarkee LOGIN;
  END IF;
END
$$;

ALTER ROLE smarkee PASSWORD 'smarkee';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
-- Provedor de localidade builtin (C.UTF-8): ordenação por ponto de código, igual em qualquer
-- sistema operacional e biblioteca C (a imagem alpine/musl e um servidor glibc ordenariam diferente).
SELECT 'CREATE DATABASE smarkee OWNER smarkee ENCODING ''UTF8'' LOCALE_PROVIDER builtin BUILTIN_LOCALE ''C.UTF-8'' LOCALE ''C.UTF-8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'smarkee') \gexec

ALTER DATABASE smarkee OWNER TO smarkee;

-- Por padrão, PUBLIC possui CONNECT e TEMPORARY em todo banco; cada serviço recebe CONNECT explicitamente.
REVOKE ALL ON DATABASE smarkee FROM PUBLIC;

\connect smarkee

-- Por padrão, PUBLIC possui USAGE no schema public; o SSOT usa um schema por módulo.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
