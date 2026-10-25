-- Migração 0001 de ipm.role: Role composta no SSOT da Smarkee (docs/POSTGRESQL.md §6 e §14.2; decisão 0083).
-- Projeto: ipm-role-manager (decisões 0015 e 0083), dono do esquema do tipo.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/ipm.sql.
-- Roles compostas (<módulo>.<tipo><Admin|Viewer>) vivem exclusivamente no SSOT da Smarkee e não
-- criam objetos no Zitadel.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.role (
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
  CONSTRAINT role_observed_generation_check
    CHECK (observed_generation IS NULL
           OR (observed_generation >= 1 AND observed_generation <= desired_generation))
);

CREATE TABLE IF NOT EXISTS ipm.role_operation (
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
CREATE INDEX IF NOT EXISTS role_operation_resource
  ON ipm.role_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS role_operation_retention
  ON ipm.role_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE IF NOT EXISTS ipm.role_action_result (
  action_id          text        PRIMARY KEY CHECK (length(action_id) BETWEEN 1 AND 512),
  resource_id        text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  action_outcome     text        NOT NULL CHECK (action_outcome IN ('completed', 'failed')),
  recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS role_action_result_recorded
  ON ipm.role_action_result (recorded_at);

CREATE TABLE IF NOT EXISTS ipm.role_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  traceparent  text        CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS role_outbox_pending
  ON ipm.role_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS role_outbox_published
  ON ipm.role_outbox (published_at) WHERE published_at IS NOT NULL;

-- Índice de unicidade de `name` entre Roles ativas (`lifecycle = 'present'`), conferido na unidade
-- atômica do pedido (docs/SSOT.md §10.1; decisão 0083).
CREATE UNIQUE INDEX IF NOT EXISTS role_active_name
  ON ipm.role ((desired ->> 'name'))
  WHERE lifecycle = 'present';

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count. `requested_by` aparece
-- só na view da Operation, para o Receiver autorizar a leitura (docs/POSTGRESQL.md §6.5).
CREATE OR REPLACE VIEW ipm.role_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM ipm.role;

CREATE OR REPLACE VIEW ipm.role_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM ipm.role_operation;

-- Roles pré-definidas da plataforma (padrão Google Cloud IAM sem prefixo `roles/`:
-- `<módulo>.<tipo><Admin|Viewer>`, decisão 0083). Protegidas contra exclusão por padrão.
WITH predefined(resource_id, role_name, description, permissions) AS (
  VALUES
    (
      'role-core-account-viewer',
      'core.accountViewer',
      'Leitura de conta pessoal em core.account.',
      '["core.account.get"]'::jsonb
    ),
    (
      'role-core-account-admin',
      'core.accountAdmin',
      'Administração da própria conta em core.account.',
      '["core.account.delete", "core.account.get"]'::jsonb
    ),
    (
      'role-sum-service-viewer',
      'sum.serviceViewer',
      'Leitura de serviços habilitados em sum.service.',
      '["sum.ipm.get"]'::jsonb
    ),
    (
      'role-sum-service-admin',
      'sum.serviceAdmin',
      'Administração de serviços habilitados em sum.service.',
      '["sum.ipm.disable", "sum.ipm.enable", "sum.ipm.get"]'::jsonb
    ),
    (
      'role-ipm-organization-viewer',
      'ipm.organizationViewer',
      'Leitura de Organizations em ipm.organization.',
      '["ipm.organization.get", "ipm.organization.list"]'::jsonb
    ),
    (
      'role-ipm-organization-admin',
      'ipm.organizationAdmin',
      'Administração de Organizations em ipm.organization.',
      '["ipm.organization.create", "ipm.organization.delete", "ipm.organization.get", "ipm.organization.list", "ipm.organization.update"]'::jsonb
    ),
    (
      'role-ipm-user-viewer',
      'ipm.userViewer',
      'Leitura de usuários organizacionais em ipm.user.',
      '["ipm.user.get", "ipm.user.list"]'::jsonb
    ),
    (
      'role-ipm-user-admin',
      'ipm.userAdmin',
      'Administração completa e delegação de permissões de usuários em ipm.user.',
      '["ipm.user.bind", "ipm.user.create", "ipm.user.delete", "ipm.user.get", "ipm.user.list", "ipm.user.update"]'::jsonb
    ),
    (
      'role-ipm-permission-viewer',
      'ipm.permissionViewer',
      'Leitura do catálogo de permissões atômicas em ipm.permission.',
      '["ipm.permission.get", "ipm.permission.list"]'::jsonb
    ),
    (
      'role-ipm-permission-admin',
      'ipm.permissionAdmin',
      'Administração do catálogo de permissões atômicas em ipm.permission.',
      '["ipm.permission.admin", "ipm.permission.get", "ipm.permission.list"]'::jsonb
    ),
    (
      'role-ipm-role-viewer',
      'ipm.roleViewer',
      'Leitura do catálogo de Roles compostas em ipm.role.',
      '["ipm.role.get", "ipm.role.list"]'::jsonb
    ),
    (
      'role-ipm-role-admin',
      'ipm.roleAdmin',
      'Administração do catálogo de Roles compostas em ipm.role.',
      '["ipm.role.admin", "ipm.role.get", "ipm.role.list"]'::jsonb
    ),
    (
      'role-bsm-account-viewer',
      'bsm.accountViewer',
      'Leitura de Billing Accounts em bsm.account.',
      '["bsm.account.get", "bsm.account.list"]'::jsonb
    ),
    (
      'role-bsm-account-admin',
      'bsm.accountAdmin',
      'Administração de Billing Accounts em bsm.account.',
      '["bsm.account.create", "bsm.account.delete", "bsm.account.get", "bsm.account.list", "bsm.account.update"]'::jsonb
    )
),
inserted AS (
  INSERT INTO ipm.role (
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
      'name', p.role_name,
      'description', p.description,
      'permissions', p.permissions,
      'deletionProtection', true
    ),
    1,
    1,
    jsonb_build_object(
      'name', p.role_name,
      'description', p.description,
      'permissions', p.permissions,
      'deletionProtection', true
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
INSERT INTO ipm.role_outbox (message_id, resource_id, subject, payload)
SELECT
  substr(md5('seed-desired-' || i.resource_id), 1, 8) || '-' ||
  substr(md5('seed-desired-' || i.resource_id), 9, 4) || '-7' ||
  substr(md5('seed-desired-' || i.resource_id), 14, 3) || '-8' ||
  substr(md5('seed-desired-' || i.resource_id), 18, 3) || '-' ||
  substr(md5('seed-desired-' || i.resource_id), 21, 12),
  i.resource_id,
  'manager.desired.ipm.role.' || i.resource_id || '.changed',
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
    'resourceType', 'role',
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
      'permissions', i.desired -> 'permissions',
      'deletionProtection', true
    )
  )
FROM inserted i
ON CONFLICT (message_id) DO NOTHING;

-- Privilégios (docs/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE ssot
  TO ipm_role_manager, ipm_role_receiver, ipm_role_publisher, ipm_maintenance;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm
  TO ipm_role_manager, ipm_role_receiver, ipm_role_publisher, ipm_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.role               TO ipm_role_manager;
GRANT SELECT, INSERT, UPDATE         ON ipm.role_operation     TO ipm_role_manager;
GRANT SELECT, INSERT                 ON ipm.role_action_result TO ipm_role_manager;
GRANT INSERT                         ON ipm.role_outbox        TO ipm_role_manager;

GRANT SELECT ON ipm.role_v1, ipm.role_operation_v1 TO ipm_role_receiver;

GRANT SELECT ON ipm.role_outbox TO ipm_role_publisher;
GRANT UPDATE (published_at) ON ipm.role_outbox TO ipm_role_publisher;

GRANT SELECT, DELETE
  ON ipm.role_outbox, ipm.role_action_result, ipm.role_operation
  TO ipm_maintenance;
