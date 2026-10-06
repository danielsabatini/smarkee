-- Papel e banco do Kong (apenas desenvolvimento local; credenciais triviais).
-- A senha deve coincidir com KONG_DATABASE_PASSWORD em gateway/.env.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'kong') THEN
    CREATE ROLE kong LOGIN;
  END IF;
END
$$;

ALTER ROLE kong PASSWORD 'kong';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
SELECT 'CREATE DATABASE kong OWNER kong'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'kong') \gexec

ALTER DATABASE kong OWNER TO kong;
