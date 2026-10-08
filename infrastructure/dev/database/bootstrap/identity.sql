-- Papel e banco do Identity (Zitadel) (apenas desenvolvimento local; credenciais triviais).
-- A senha deve coincidir com ZITADEL_DATABASE_POSTGRES_USER_PASSWORD em identity/.env.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'identity') THEN
    CREATE ROLE identity LOGIN;
  END IF;
END
$$;

ALTER ROLE identity PASSWORD 'identity';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
SELECT 'CREATE DATABASE identity OWNER identity'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'identity') \gexec

ALTER DATABASE identity OWNER TO identity;
