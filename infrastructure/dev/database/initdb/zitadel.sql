-- Papel e banco do Zitadel (apenas desenvolvimento local; credenciais triviais).
-- A senha deve coincidir com ZITADEL_DATABASE_PASSWORD em identity/.env.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'zitadel') THEN
    CREATE ROLE zitadel LOGIN;
  END IF;
END
$$;

ALTER ROLE zitadel PASSWORD 'zitadel';

-- CREATE DATABASE não aceita bloco condicional; \gexec executa só se o banco não existir.
SELECT 'CREATE DATABASE zitadel OWNER zitadel'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zitadel') \gexec

ALTER DATABASE zitadel OWNER TO zitadel;
