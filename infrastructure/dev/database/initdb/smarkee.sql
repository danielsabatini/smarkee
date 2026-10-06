-- Proprietário e banco do SSOT (apenas desenvolvimento local; credenciais triviais).
-- Conforme docs/POSTGRESQL.md: banco único `smarkee`, proprietário `smarkee_owner` (não superusuário),
-- usado somente por migração e recuperação. Papéis de serviço são criados pelas migrações de cada tipo.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'smarkee_owner') THEN
    CREATE ROLE smarkee_owner LOGIN;
  END IF;
END
$$;

ALTER ROLE smarkee_owner PASSWORD 'smarkee';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
SELECT 'CREATE DATABASE smarkee OWNER smarkee_owner ENCODING ''UTF8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'smarkee') \gexec

ALTER DATABASE smarkee OWNER TO smarkee_owner;

-- Por padrão, PUBLIC possui CONNECT e TEMPORARY em todo banco; cada serviço recebe CONNECT explicitamente.
REVOKE ALL ON DATABASE smarkee FROM PUBLIC;

\connect smarkee

-- Por padrão, PUBLIC possui USAGE no schema public; o SSOT usa um schema por módulo.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
