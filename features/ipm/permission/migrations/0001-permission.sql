-- Migração 0001 de ipm.permission: Permissão atômica no SSOT da Smarkee (docs/POSTGRESQL.md §6 e §14.2; decisão 0083).
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
-- unidade atômica do pedido (docs/SSOT.md §10.1; decisão 0083).
CREATE UNIQUE INDEX IF NOT EXISTS permission_active_name
  ON ipm.permission ((desired ->> 'name'))
  WHERE lifecycle = 'present';

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count. `requested_by`
-- aparece só na view da Operation, para o Receiver autorizar a leitura (docs/POSTGRESQL.md §6.5).
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
    ('perm-bsm-account-create', 'bsm.account.create', 'bsm', 'Criar Billing Accounts', false),
    ('perm-bsm-account-delete', 'bsm.account.delete', 'bsm', 'Remover Billing Accounts', false),
    ('perm-bsm-account-get',    'bsm.account.get',    'bsm', 'Ler Billing Accounts', false),
    ('perm-bsm-account-list',   'bsm.account.list',   'bsm', 'Listar Billing Accounts', false),
    ('perm-bsm-account-update', 'bsm.account.update', 'bsm', 'Alterar Billing Accounts', false),
    ('perm-bsm-account-admin',  'bsm.account.admin',  'bsm', 'Operador: qualquer Billing Account', false),
    -- core.account (roles-core): nível de conta pessoal (register)
    ('perm-core-account-delete', 'core.account.delete', 'core', 'Remover a própria conta', false),
    ('perm-core-account-get',    'core.account.get',    'core', 'Ler a própria conta', false),
    ('perm-core-account-admin',  'core.account.admin',  'core', 'Operador: qualquer conta', false),
    -- sum.ipm (roles-sum): nível de conta pessoal (register)
    ('perm-sum-ipm-disable', 'sum.ipm.disable', 'sum', 'Desabilitar o módulo IPM da conta', false),
    ('perm-sum-ipm-enable',  'sum.ipm.enable',  'sum', 'Habilitar o módulo IPM da conta', false),
    ('perm-sum-ipm-get',     'sum.ipm.get',     'sum', 'Ler o estado do módulo IPM da conta', false),
    -- ipm.organization (roles-ipm): create/delete são da conta pessoal; get/list/update são delegáveis à Organization
    ('perm-ipm-organization-create', 'ipm.organization.create', 'ipm', 'Criar Organizations', false),
    ('perm-ipm-organization-delete', 'ipm.organization.delete', 'ipm', 'Remover Organizations', false),
    ('perm-ipm-organization-get',    'ipm.organization.get',    'ipm', 'Ler Organizations', true),
    ('perm-ipm-organization-list',   'ipm.organization.list',   'ipm', 'Listar Organizations', true),
    ('perm-ipm-organization-update', 'ipm.organization.update', 'ipm', 'Alterar Organizations', true),
    ('perm-ipm-organization-admin',  'ipm.organization.admin',  'ipm', 'Operador: qualquer Organization', false),
    -- ipm.user (roles-ipm): delegáveis à Organization (exceto admin)
    ('perm-ipm-user-bind',   'ipm.user.bind',   'ipm', 'Atribuir e alterar permissões de usuários da Organization', true),
    ('perm-ipm-user-create', 'ipm.user.create', 'ipm', 'Criar usuários da Organization', true),
    ('perm-ipm-user-delete', 'ipm.user.delete', 'ipm', 'Remover usuários da Organization', true),
    ('perm-ipm-user-get',    'ipm.user.get',    'ipm', 'Ler usuários da Organization', true),
    ('perm-ipm-user-list',   'ipm.user.list',   'ipm', 'Listar usuários da Organization', true),
    ('perm-ipm-user-update', 'ipm.user.update', 'ipm', 'Alterar usuários da Organization', true),
    ('perm-ipm-user-admin',  'ipm.user.admin',  'ipm', 'Operador: qualquer usuário da Organization', false),
    -- ipm.permission (roles-ipm): catálogo global da plataforma
    ('perm-ipm-permission-get',   'ipm.permission.get',   'ipm', 'Ler permissões do catálogo da plataforma', false),
    ('perm-ipm-permission-list',  'ipm.permission.list',  'ipm', 'Listar permissões do catálogo da plataforma', false),
    ('perm-ipm-permission-admin', 'ipm.permission.admin', 'ipm', 'Operador: gerenciar o catálogo de permissões', false),
    -- ipm.role (roles-ipm): catálogo global da plataforma
    ('perm-ipm-role-get',   'ipm.role.get',   'ipm', 'Ler Roles compostas do catálogo da plataforma', false),
    ('perm-ipm-role-list',  'ipm.role.list',  'ipm', 'Listar Roles compostas do catálogo da plataforma', false),
    ('perm-ipm-role-admin', 'ipm.role.admin', 'ipm', 'Operador: gerenciar o catálogo de Roles compostas', false)
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
  ON CONFLICT (resource_id) DO NOTHING
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
  'manager.desired.ipm.permission.' || i.resource_id || '.changed',
  jsonb_build_object(
    'messageId',
      substr(md5('seed-desired-' || i.resource_id), 1, 8) || '-' ||
      substr(md5('seed-desired-' || i.resource_id), 9, 4) || '-7' ||
      substr(md5('seed-desired-' || i.resource_id), 14, 3) || '-8' ||
      substr(md5('seed-desired-' || i.resource_id), 18, 3) || '-' ||
      substr(md5('seed-desired-' || i.resource_id), 21, 12),
    'schemaVersion', '1.0',
    'messageType', 'desired',
    'emitter', 'manager',
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

-- Privilégios (docs/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE ssot
  TO ipm_permission_manager, ipm_permission_receiver, ipm_permission_publisher, ipm_maintenance;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm
  TO ipm_permission_manager, ipm_permission_receiver, ipm_permission_publisher, ipm_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.permission               TO ipm_permission_manager;
GRANT SELECT, INSERT, UPDATE         ON ipm.permission_operation     TO ipm_permission_manager;
GRANT SELECT, INSERT                 ON ipm.permission_action_result TO ipm_permission_manager;
GRANT INSERT                         ON ipm.permission_outbox        TO ipm_permission_manager;

GRANT SELECT ON ipm.permission_v1, ipm.permission_operation_v1 TO ipm_permission_receiver;

GRANT SELECT ON ipm.permission_outbox TO ipm_permission_publisher;
GRANT UPDATE (published_at) ON ipm.permission_outbox TO ipm_permission_publisher;

GRANT SELECT, DELETE
  ON ipm.permission_outbox, ipm.permission_action_result, ipm.permission_operation
  TO ipm_maintenance;
