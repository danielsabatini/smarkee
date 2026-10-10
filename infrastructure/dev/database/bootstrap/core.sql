-- Papéis do módulo core no SSOT (apenas desenvolvimento local; credenciais triviais).
-- Conforme docs/POSTGRESQL.md §14.2 e §14.3: um papel de função sem login por serviço, que recebe
-- os privilégios (concedidos pela migração do módulo, como dono `smarkee`), e um papel de login por
-- serviço, membro do papel de função, com os parâmetros de sessão.
-- Criar papéis exige CREATEROLE: por isso roda como administrador, e não na migração.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
DECLARE
  function_role text;
BEGIN
  FOREACH function_role IN ARRAY ARRAY[
    'core_organization_manager', 'core_organization_api', 'core_user_manager', 'core_user_api',
    'core_relay', 'core_maintenance'
  ] LOOP
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = function_role) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', function_role);
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = function_role || '_login') THEN
      EXECUTE format('CREATE ROLE %I LOGIN', function_role || '_login');
    END IF;
    -- Senha trivial de dev, igual ao nome do papel de login.
    EXECUTE format('ALTER ROLE %I PASSWORD %L', function_role || '_login', function_role || '_login');
    EXECUTE format('GRANT %I TO %I', function_role, function_role || '_login');
    -- Parâmetros de sessão no papel de login (os do papel de função não se aplicam a quem o herda).
    EXECUTE format('ALTER ROLE %I SET search_path = %L', function_role || '_login', '');
    EXECUTE format('ALTER ROLE %I SET lock_timeout = %L', function_role || '_login', '2s');
    EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', function_role || '_login', '5s');
    EXECUTE format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', function_role || '_login', '10s');
  END LOOP;
END
$$;
