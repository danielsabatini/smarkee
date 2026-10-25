-- Papel de telemetria do PostgreSQL (apenas desenvolvimento local; credenciais triviais).
-- Segue o princípio do menor privilégio (AGENTS.md §4.2):
--   1. `pg_read_all_stats` permite ao `postgresqlreceiver` ler `pg_stat_*` e `pg_database_size()`
--      sem acesso de leitura aos dados das tabelas de negócio (`pg_read_all_data` NUNCA é concedido).
--   2. A função `telemetry.outbox_stats()` (`SECURITY DEFINER`, de propriedade de `smarkee`)
--      descobre dinamicamente as tabelas `*_outbox` do SSOT e devolve apenas a contagem e a idade
--      (em segundos) das mensagens pendentes (`published_at IS NULL`), sem expor `payload` e sem
--      acoplar o `telemetry-agent` à lista de features.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telemetry') THEN
    CREATE ROLE telemetry NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telemetry_login') THEN
    CREATE ROLE telemetry_login LOGIN;
  END IF;
END
$$;

ALTER ROLE telemetry_login PASSWORD 'telemetry_login';
GRANT telemetry TO telemetry_login;
GRANT pg_read_all_stats TO telemetry;

ALTER ROLE telemetry_login SET search_path = 'pg_catalog';
ALTER ROLE telemetry_login SET lock_timeout = '2s';
ALTER ROLE telemetry_login SET statement_timeout = '5s';
ALTER ROLE telemetry_login SET idle_in_transaction_session_timeout = '10s';

GRANT CONNECT ON DATABASE smarkee TO telemetry;
GRANT CONNECT ON DATABASE identity TO telemetry;
GRANT CONNECT ON DATABASE platform TO telemetry;

\connect smarkee

CREATE SCHEMA IF NOT EXISTS telemetry AUTHORIZATION smarkee;
REVOKE ALL ON SCHEMA telemetry FROM PUBLIC;
GRANT USAGE ON SCHEMA telemetry TO telemetry;

CREATE OR REPLACE FUNCTION telemetry.outbox_stats()
RETURNS TABLE (
  "db.namespace" text,
  "db.collection.name" text,
  unpublished_messages bigint,
  oldest_unpublished_age double precision
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
  rec record;
BEGIN
  FOR rec IN
    SELECT n.nspname AS schema_name, c.relname AS table_name
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind = 'r'
       AND c.relname LIKE '%\_outbox' ESCAPE '\'
       AND pg_catalog.pg_get_userbyid(c.relowner) = 'smarkee'
     ORDER BY n.nspname, c.relname
  LOOP
    RETURN QUERY EXECUTE pg_catalog.format(
      'SELECT %L::text, %L::text, count(*)::bigint, '
      'COALESCE(EXTRACT(EPOCH FROM (pg_catalog.now() - pg_catalog.min(created_at)))::double precision, 0.0) '
      'FROM %I.%I WHERE published_at IS NULL',
      'smarkee|' || rec.schema_name,
      rec.table_name,
      rec.schema_name,
      rec.table_name
    );
  END LOOP;
END;
$function$;

ALTER FUNCTION telemetry.outbox_stats() OWNER TO smarkee;
REVOKE ALL ON FUNCTION telemetry.outbox_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION telemetry.outbox_stats() TO telemetry;
