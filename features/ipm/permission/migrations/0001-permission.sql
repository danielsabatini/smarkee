-- Migração 0001 de ipm.permission: Permissão atômica no SSOT da Smarkee (docs/data/POSTGRESQL.md §6 e §14.2; decisão 0083).
-- Projeto: ipm-permission-manager (decisões 0015 e 0083), dono do esquema do tipo.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/ipm.sql.
-- Cada Permission (`<módulo>.<tipo>.<ação>`) é reconciliada pelo ipm-permission-executor com o
-- projeto `roles-<módulo>` na organização `core` do Zitadel.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.permission (
  resource_id         text        PRIMARY KEY
                      CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  schema_version      text        NOT NULL CHECK (schema_version ~ '^[0-9]+\.[0-9]+$'),
  lifecycle           text        NOT NULL CHECK (lifecycle IN ('present', 'absent')),
  reconciliation      text        NOT NULL DEFAULT 'active' CHECK (reconciliation IN ('active', 'suspended')),
  desired             jsonb       NOT NULL
                      CHECK (jsonb_typeof(desired) = 'object' AND pg_column_size(desired) <= 262144),
  desired_generation  bigint      NOT NULL CHECK (desired_generation >= 1),
  resource_version    bigint      NOT NULL DEFAULT 1,
  observed            jsonb
                      CHECK (observed IS NULL OR (jsonb_typeof(observed) = 'object' AND pg_column_size(observed) <= 262144)),
  presence            text        CHECK (presence IN ('present', 'absent', 'unknown')),
  observed_at         timestamptz,
  phase               text        NOT NULL CHECK (phase IN ('Pending', 'Reconciling', 'Ready', 'Failed', 'Deleting')),
  conditions          jsonb       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(conditions) = 'array'),
  failure_count       integer     NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  observed_generation bigint,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CHECK ((presence IS NULL) = (observed_at IS NULL)),
  CONSTRAINT permission_observed_generation_check
    CHECK (observed_generation IS NULL
           OR (observed_generation >= 1 AND observed_generation <= desired_generation))
);

CREATE TABLE IF NOT EXISTS ipm.permission_operation (
  operation_id            text        PRIMARY KEY CHECK (length(operation_id) BETWEEN 1 AND 128),
  resource_id             text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  operation_type          text        NOT NULL CHECK (operation_type IN ('create', 'update', 'delete')),
  desired_generation      bigint      CHECK (desired_generation >= 1),
  requested_by            text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  correlation_id          text        NOT NULL CHECK (length(correlation_id) BETWEEN 1 AND 256),
  request_digest          text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  operation_status        text        NOT NULL
                          CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected')),
  operation_status_reason text        CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found', 'protected')),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  completed_at            timestamptz,
  CHECK ((operation_status = 'rejected') = (operation_status_reason IS NOT NULL)),
  CHECK ((operation_status = 'rejected') = (desired_generation IS NULL))
);
CREATE INDEX IF NOT EXISTS permission_operation_resource
  ON ipm.permission_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS permission_operation_retention
  ON ipm.permission_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE IF NOT EXISTS ipm.permission_action_result (
  action_id          text        PRIMARY KEY CHECK (length(action_id) BETWEEN 1 AND 512),
  resource_id        text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  action_outcome     text        NOT NULL CHECK (action_outcome IN ('completed', 'failed')),
  recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS permission_action_result_recorded
  ON ipm.permission_action_result (recorded_at);

CREATE TABLE IF NOT EXISTS ipm.permission_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  traceparent  text        CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS permission_outbox_pending
  ON ipm.permission_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS permission_outbox_published
  ON ipm.permission_outbox (published_at) WHERE published_at IS NOT NULL;

-- Índice de unicidade de `name` entre Permissions ativas (`lifecycle = 'present'`), conferido na
-- unidade atômica do pedido (docs/data/SSOT.md §10.1; decisão 0083).
CREATE UNIQUE INDEX IF NOT EXISTS permission_active_name
  ON ipm.permission ((desired ->> 'name'))
  WHERE lifecycle = 'present';

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count. `requested_by`
-- aparece só na view da Operation, para o Receiver autorizar a leitura (docs/data/POSTGRESQL.md §6.5).
DROP VIEW IF EXISTS ipm.permission_v1;
CREATE OR REPLACE VIEW ipm.permission_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM ipm.permission;

CREATE OR REPLACE VIEW ipm.permission_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM ipm.permission_operation;

-- Permissões atômicas pré-definidas da plataforma (`<módulo>.<tipo>.<ação>`, decisões 0028 e 0083).
WITH predefined(resource_id, permission_name, module_group, description, grantable) AS (
  VALUES
    -- bsm.account (roles-bsm): nível de conta pessoal (register)
    ('01a1763d-eb05-7408-8945-8b7798b1f584', 'bsm.account.create', 'bsm', 'Criar Billing Accounts', false),
    ('01a1763d-eb07-73a3-9238-cebddc755e48', 'bsm.account.delete', 'bsm', 'Remover Billing Accounts', false),
    ('01a1763d-eb0a-73e6-ae87-09479da576ee',    'bsm.account.get',    'bsm', 'Ler Billing Accounts', false),
    ('01a1763d-eb0c-71d0-82c7-3010ed561cc5',   'bsm.account.list',   'bsm', 'Listar Billing Accounts', false),
    ('01a1763d-eb0f-75ea-8b0f-8bf1afb324fa', 'bsm.account.update', 'bsm', 'Alterar Billing Accounts', false),
    ('01a1763d-eb11-715e-96bb-90b4ab137e28',  'bsm.account.admin',  'bsm', 'Operador: qualquer Billing Account', false),
    -- core.account (roles-core): nível de conta pessoal (register)
    ('01a1763d-eb14-74eb-86dd-6f7f4b480783', 'core.account.delete', 'core', 'Remover a própria conta', false),
    ('01a1763d-eb16-748d-bafc-dd2976ec27a4',    'core.account.get',    'core', 'Ler a própria conta', false),
    ('01a1763d-eb19-737d-9a93-d95b72ff01c0',  'core.account.admin',  'core', 'Operador: qualquer conta', false),
    -- sum.ipm (roles-sum): nível de conta pessoal (register)
    ('01a1763d-eb1c-70bf-bf6c-8e2bb3bed9ec', 'sum.ipm.disable', 'sum', 'Desabilitar o módulo IPM da conta', false),
    ('01a1763d-eb1e-7411-939c-a0f773e2f875',  'sum.ipm.enable',  'sum', 'Habilitar o módulo IPM da conta', false),
    ('01a1763d-eb21-7647-aa8d-66b6fe110cf3',     'sum.ipm.get',     'sum', 'Ler o estado do módulo IPM da conta', false),
    -- ipm.organization (roles-ipm): create/delete são da conta pessoal; get/list/update são delegáveis à Organization
    ('01a1763d-eb23-7095-9112-0b521899e026', 'ipm.organization.create', 'ipm', 'Criar Organizations', false),
    ('01a1763d-eb26-7392-b4a7-e3ed5a955cce', 'ipm.organization.delete', 'ipm', 'Remover Organizations', false),
    ('01a1763d-eb28-773d-804c-1779722fbb95',    'ipm.organization.get',    'ipm', 'Ler Organizations', true),
    ('01a1763d-eb2a-716f-9417-5dc1e3d3264f',   'ipm.organization.list',   'ipm', 'Listar Organizations', true),
    ('01a1763d-eb2d-726e-b505-3592ecdff4d6', 'ipm.organization.update', 'ipm', 'Alterar Organizations', true),
    ('01a1763d-eb2f-73e4-8e15-29bb53ca2855',  'ipm.organization.admin',  'ipm', 'Operador: qualquer Organization', false),
    -- ipm.user (roles-ipm): delegáveis à Organization (exceto admin)
    ('01a1763d-eb32-73e1-b31b-44a5a2a7669a',   'ipm.user.bind',   'ipm', 'Atribuir e alterar permissões de usuários da Organization', true),
    ('01a1763d-eb34-7534-8d01-569b74847fcc', 'ipm.user.create', 'ipm', 'Criar usuários da Organization', true),
    ('01a1763d-eb37-721a-8ac9-9aaa0550c7ea', 'ipm.user.delete', 'ipm', 'Remover usuários da Organization', true),
    ('01a1763d-eb39-7341-8c3b-43b5c7f9ade5',    'ipm.user.get',    'ipm', 'Ler usuários da Organization', true),
    ('01a1763d-eb3c-747c-86fe-8f34692042e2',   'ipm.user.list',   'ipm', 'Listar usuários da Organization', true),
    ('01a1763d-eb3e-72dd-b96c-015c189af10b', 'ipm.user.update', 'ipm', 'Alterar usuários da Organization', true),
    ('01a1763d-eb40-71a5-ab70-96207a5b4d2d',  'ipm.user.admin',  'ipm', 'Operador: qualquer usuário da Organization', false),
    -- ipm.permission (roles-ipm): catálogo global da plataforma
    ('01a1763d-eb43-703d-a168-aa3ade79c4f8',   'ipm.permission.get',   'ipm', 'Ler permissões do catálogo da plataforma', false),
    ('01a1763d-eb45-7247-ab1a-90fdc45b217d',  'ipm.permission.list',  'ipm', 'Listar permissões do catálogo da plataforma', false),
    ('01a1763d-eb48-728c-ade2-0dbe753f70de', 'ipm.permission.admin', 'ipm', 'Operador: gerenciar o catálogo de permissões', false),
    -- ipm.role (roles-ipm): predefinidas da plataforma e custom da Organization (decisão 0092)
    ('01a1763d-eb4a-7168-981a-0862f72aeeca',   'ipm.role.get',   'ipm', 'Ler Roles compostas da plataforma e da Organization', true),
    ('01a1763d-eb4d-750a-b163-4e082cff09ee',  'ipm.role.list',  'ipm', 'Listar Roles compostas da plataforma e da Organization', true),
    ('01a1786d-a738-7610-9de8-ad451bbbb39f', 'ipm.role.create', 'ipm', 'Criar Roles custom da Organization', true),
    ('01a1786d-a73c-7407-9e1a-50d78bdba2a5', 'ipm.role.update', 'ipm', 'Alterar Roles custom da Organization', true),
    ('01a1786d-a740-7674-91a7-6deb899bffd3', 'ipm.role.delete', 'ipm', 'Excluir Roles custom da Organization', true),
    ('01a1786d-a743-766f-862d-8b431ae57347', 'ipm.role.bind', 'ipm', 'Definir e alterar as permissões de Roles custom da Organization', true),
    ('01a1763d-eb4f-71f6-ad10-991a7f90c40a', 'ipm.role.admin', 'ipm', 'Operador: gerenciar o catálogo de Roles compostas', false),
    -- ipm.group (roles-ipm): delegáveis à Organization (exceto admin)
    ('01a17641-4895-761f-888f-24ca35143f79', 'ipm.group.create', 'ipm', 'Criar grupos de usuários da Organization', true),
    ('01a17641-4897-73c9-adf3-a0ddcf0e27d3', 'ipm.group.delete', 'ipm', 'Excluir grupos de usuários da Organization', true),
    ('01a17641-489a-7615-848c-3263328fedc0', 'ipm.group.get', 'ipm', 'Ler grupos de usuários da Organization', true),
    ('01a17641-489c-75c9-81c4-34e1ce2459a7', 'ipm.group.list', 'ipm', 'Listar grupos de usuários da Organization', true),
    ('01a17641-489f-72ea-9647-b39cb4237b52', 'ipm.group.update', 'ipm', 'Alterar grupos de usuários da Organization', true),
    ('01a17641-48a1-77c5-9e35-69e7e1b1706f', 'ipm.group.bind', 'ipm', 'Atribuir e alterar roles de grupos de usuários da Organization', true),
    ('01a17641-48a4-7790-9a6c-25f5aaea438c', 'ipm.group.admin', 'ipm', 'Operador: gerenciar qualquer grupo', false),
    -- ipm.serviceaccount (roles-ipm): delegáveis à Organization (exceto admin), decisão 0094
    ('01a179e8-9222-762f-859b-b71c8ea23477', 'ipm.serviceaccount.create', 'ipm', 'Criar service accounts da Organization', true),
    ('01a179e8-9225-7f05-9cb3-a887a2614955', 'ipm.serviceaccount.delete', 'ipm', 'Excluir service accounts da Organization', true),
    ('01a179e8-9228-7ffb-b962-6041f9f195b6', 'ipm.serviceaccount.get', 'ipm', 'Ler service accounts da Organization', true),
    ('01a179e8-922b-7c5e-b950-cae0d554ae40', 'ipm.serviceaccount.list', 'ipm', 'Listar service accounts da Organization', true),
    ('01a179e8-922e-7575-98cc-e70de27d328c', 'ipm.serviceaccount.update', 'ipm', 'Alterar service accounts da Organization', true),
    ('01a179e8-9231-77ac-8d48-8958a211148a', 'ipm.serviceaccount.bind', 'ipm', 'Atribuir e alterar roles e chaves de service accounts da Organization', true),
    ('01a179e8-9234-78e2-a930-b7b782effe5c', 'ipm.serviceaccount.admin', 'ipm', 'Operador: gerenciar qualquer service account', false)
),
inserted AS (
  INSERT INTO ipm.permission (
    resource_id,
    schema_version,
    lifecycle,
    reconciliation,
    desired,
    desired_generation,
    resource_version,
    observed,
    presence,
    observed_at,
    phase,
    conditions,
    observed_generation
  )
  SELECT
    p.resource_id,
    '1.0',
    'present',
    'active',
    jsonb_build_object(
      'lifecycle', 'present',
      'name', p.permission_name,
      'description', p.description,
      'grantable', p.grantable,
      'deletionProtection', true
    ),
    1,
    1,
    jsonb_build_object(
      'name', p.permission_name,
      'description', p.description,
      'group', p.module_group
    ),
    'present',
    now(),
    'Ready',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'Ready',
        'status', 'True',
        'reason', 'Converged',
        'message', 'O estado observado corresponde ao estado desejado.',
        'observedGeneration', 1,
        'lastTransitionAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      ),
      jsonb_build_object(
        'type', 'Progressing',
        'status', 'False',
        'reason', 'Converged',
        'message', 'Nenhuma reconciliação em andamento.',
        'observedGeneration', 1,
        'lastTransitionAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      ),
      jsonb_build_object(
        'type', 'Degraded',
        'status', 'False',
        'reason', 'Healthy',
        'message', 'Sem falhas na geração atual.',
        'observedGeneration', 1,
        'lastTransitionAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      )
    ),
    1
  FROM predefined p
  ON CONFLICT DO NOTHING
  RETURNING resource_id, desired
)
INSERT INTO ipm.permission_outbox (message_id, resource_id, subject, payload)
SELECT
  substr(md5('seed-desired-' || i.resource_id), 1, 8) || '-' ||
  substr(md5('seed-desired-' || i.resource_id), 9, 4) || '-7' ||
  substr(md5('seed-desired-' || i.resource_id), 14, 3) || '-8' ||
  substr(md5('seed-desired-' || i.resource_id), 18, 3) || '-' ||
  substr(md5('seed-desired-' || i.resource_id), 21, 12),
  i.resource_id,
  'desired.ipm.permission.' || i.resource_id,
  jsonb_build_object(
    'messageId',
      substr(md5('seed-desired-' || i.resource_id), 1, 8) || '-' ||
      substr(md5('seed-desired-' || i.resource_id), 9, 4) || '-7' ||
      substr(md5('seed-desired-' || i.resource_id), 14, 3) || '-8' ||
      substr(md5('seed-desired-' || i.resource_id), 18, 3) || '-' ||
      substr(md5('seed-desired-' || i.resource_id), 21, 12),
    'schemaVersion', '1.0',
    'messageType', 'desired',
    'emitter', 'api',
    'module', 'ipm',
    'resourceType', 'permission',
    'resourceId', i.resource_id,
    'operation', 'changed',
    'desiredGeneration', 1,
    'requestedBy', 'system',
    'correlationId',
      substr(md5('seed-correlation-' || i.resource_id), 1, 8) || '-' ||
      substr(md5('seed-correlation-' || i.resource_id), 9, 4) || '-7' ||
      substr(md5('seed-correlation-' || i.resource_id), 14, 3) || '-8' ||
      substr(md5('seed-correlation-' || i.resource_id), 18, 3) || '-' ||
      substr(md5('seed-correlation-' || i.resource_id), 21, 12),
    'causationId',
      substr(md5('seed-causation-' || i.resource_id), 1, 8) || '-' ||
      substr(md5('seed-causation-' || i.resource_id), 9, 4) || '-7' ||
      substr(md5('seed-causation-' || i.resource_id), 14, 3) || '-8' ||
      substr(md5('seed-causation-' || i.resource_id), 18, 3) || '-' ||
      substr(md5('seed-causation-' || i.resource_id), 21, 12),
    'occurredAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'data', jsonb_build_object(
      'lifecycle', 'present',
      'reconciliation', 'active',
      'name', i.desired -> 'name',
      'description', i.desired -> 'description',
      'grantable', i.desired -> 'grantable',
      'deletionProtection', true
    )
  )
FROM inserted i
ON CONFLICT (message_id) DO NOTHING;

-- Privilégios (docs/data/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE ssot
  TO ipm_permission_publisher, ipm_maintenance;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm
  TO ipm_permission_publisher, ipm_maintenance;



GRANT SELECT ON ipm.permission_outbox TO ipm_permission_publisher;
GRANT UPDATE (published_at) ON ipm.permission_outbox TO ipm_permission_publisher;

GRANT SELECT, DELETE
  ON ipm.permission_outbox, ipm.permission_action_result, ipm.permission_operation
  TO ipm_maintenance;
