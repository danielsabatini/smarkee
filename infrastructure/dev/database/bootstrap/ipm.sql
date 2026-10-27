-- Papéis do módulo ipm no SSOT (apenas desenvolvimento local; credenciais triviais).
-- Um papel por componente de cada tipo, inclusive o publisher (decisão 0015).
-- Conforme docs/data/POSTGRESQL.md §14.2 e §14.3: um papel de função sem login por serviço, que recebe
-- os privilégios (concedidos pela migração do módulo, como dono `ssot`), e um papel de login por
-- serviço, membro do papel de função, com os parâmetros de sessão.
-- Criar papéis exige CREATEROLE: por isso roda como administrador, e não na migração.
-- Idempotente: pode ser reaplicado sem erro.

DO $$
DECLARE
  function_role text;
BEGIN
  FOREACH function_role IN ARRAY ARRAY[
    'ipm_group_manager', 'ipm_group_receiver', 'ipm_group_publisher',
    -- Plano de dados (banco `platform`): Executor lê e escreve; Observer só lê.
    'ipm_group_executor', 'ipm_group_observer',
    'ipm_organization_manager', 'ipm_organization_receiver', 'ipm_organization_publisher',
    -- Controller (decisão 0096): reconcilia o recurso externo e grava o estado observado.
    'ipm_organization_controller', 'ipm_serviceaccount_controller', 'ipm_user_controller',
    'ipm_permission_manager', 'ipm_permission_receiver', 'ipm_permission_publisher',
    'ipm_role_manager', 'ipm_role_receiver', 'ipm_role_publisher',
    -- Plano de dados (banco `platform`): Executor lê e escreve; Observer só lê.
    'ipm_role_executor', 'ipm_role_observer',
    -- API síncrona (decisão 0098): admissão na requisição, no lugar de Receiver e Manager.
    'ipm_serviceaccount_api', 'ipm_serviceaccount_publisher',
    'ipm_user_api', 'ipm_user_publisher',
    'ipm_maintenance'
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
