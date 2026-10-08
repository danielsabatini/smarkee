-- Papel e banco do Gateway (Kong) (apenas desenvolvimento local; credenciais triviais).
-- A senha deve coincidir com KONG_DATABASE_PASSWORD em gateway/.env.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gateway') THEN
    CREATE ROLE gateway LOGIN;
  END IF;
END
$$;

ALTER ROLE gateway PASSWORD 'gateway';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
SELECT 'CREATE DATABASE gateway OWNER gateway'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gateway') \gexec

ALTER DATABASE gateway OWNER TO gateway;
