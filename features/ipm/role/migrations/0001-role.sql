-- Migração 0001 de ipm.role: Role composta no SSOT da Smarkee (docs/data/POSTGRESQL.md §6 e §14.2; decisão 0083).
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
-- atômica do pedido (docs/data/SSOT.md §10.1; decisão 0083).
-- Desde a decisão 0092 a unicidade é por Organization; a 0004 remove o índice antigo (só por `name`).
CREATE UNIQUE INDEX IF NOT EXISTS role_active_organization_name
  ON ipm.role ((desired ->> 'organizationId'), (desired ->> 'name'))
  WHERE lifecycle = 'present';

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count. `requested_by` aparece
-- só na view da Operation, para o Receiver autorizar a leitura (docs/data/POSTGRESQL.md §6.5).
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
      '01a1763d-eb52-748b-84c3-10fa2192a062',
      'core.accountViewer',
      'Leitura de conta pessoal em core.account.',
      '["core.account.get"]'::jsonb
    ),
    (
      '01a1763d-eb54-762f-813e-15a4667086f1',
      'core.accountAdmin',
      'Administração da própria conta em core.account.',
      '["core.account.delete", "core.account.get"]'::jsonb
    ),
    (
      '01a1763d-eb57-7009-9196-741d0a8702ab',
      'sum.serviceViewer',
      'Leitura de serviços habilitados em sum.service.',
      '["sum.ipm.get"]'::jsonb
    ),
    (
      '01a1763d-eb59-715e-bfd5-129f757b2768',
      'sum.serviceAdmin',
      'Administração de serviços habilitados em sum.service.',
      '["sum.ipm.disable", "sum.ipm.enable", "sum.ipm.get"]'::jsonb
    ),
    (
      '01a1763d-eb5c-75f1-b729-da3469748023',
      'ipm.organizationViewer',
      'Leitura de Organizations em ipm.organization.',
      '["ipm.organization.get", "ipm.organization.list"]'::jsonb
    ),
    (
      '01a1763d-eb5e-76c7-9ee2-ff8583f80d5f',
      'ipm.organizationAdmin',
      'Administração de Organizations em ipm.organization.',
      '["ipm.organization.create", "ipm.organization.delete", "ipm.organization.get", "ipm.organization.list", "ipm.organization.update"]'::jsonb
    ),
    (
      '01a1763d-eb61-7251-90a6-ba7f921db3f1',
      'ipm.userViewer',
      'Leitura de usuários organizacionais em ipm.user.',
      '["ipm.user.get", "ipm.user.list"]'::jsonb
    ),
    (
      '01a1763d-eb63-7386-90c5-388bcb125747',
      'ipm.userAdmin',
      'Administração completa e delegação de permissões de usuários em ipm.user.',
      '["ipm.user.bind", "ipm.user.create", "ipm.user.delete", "ipm.user.get", "ipm.user.list", "ipm.user.update"]'::jsonb
    ),
    (
      '01a1763d-eb66-72a8-b4e3-b67bddd33abb',
      'ipm.permissionViewer',
      'Leitura do catálogo de permissões atômicas em ipm.permission.',
      '["ipm.permission.get", "ipm.permission.list"]'::jsonb
    ),
    (
      '01a1763d-eb68-74e5-a6ad-678e9ae3beed',
      'ipm.permissionAdmin',
      'Administração do catálogo de permissões atômicas em ipm.permission.',
      '["ipm.permission.admin", "ipm.permission.get", "ipm.permission.list"]'::jsonb
    ),
    (
      '01a1763d-eb6b-7741-9f74-08d54a0347d0',
      'ipm.roleViewer',
      'Leitura do catálogo de Roles compostas em ipm.role.',
      '["ipm.role.get", "ipm.role.list"]'::jsonb
    ),
    (
      '01a1763d-eb6d-73a1-bdc9-a3f97c7560aa',
      'ipm.roleAdmin',
      'Administração do catálogo de Roles compostas em ipm.role.',
      '["ipm.role.admin", "ipm.role.get", "ipm.role.list"]'::jsonb
    ),
    (
      '01a1763d-eb70-73f1-84a5-b0ffa6a01b3a',
      'bsm.accountViewer',
      'Leitura de Billing Accounts em bsm.account.',
      '["bsm.account.get", "bsm.account.list"]'::jsonb
    ),
    (
      '01a1763d-eb72-714d-b94d-651adccd509f',
      'bsm.accountAdmin',
      'Administração de Billing Accounts em bsm.account.',
      '["bsm.account.create", "bsm.account.delete", "bsm.account.get", "bsm.account.list", "bsm.account.update"]'::jsonb
    ),
    (
      '01a17641-48a6-7106-88be-dc31ff14f340',
      'ipm.groupViewer',
      'Leitura de grupos de usuários em ipm.group.',
      '["ipm.group.get", "ipm.group.list"]'::jsonb
    ),
    (
      '01a17641-48a9-7074-a84a-6ae0dc0651c4',
      'ipm.groupAdmin',
      'Administração de grupos de usuários em ipm.group.',
      '["ipm.group.bind", "ipm.group.create", "ipm.group.delete", "ipm.group.get", "ipm.group.list", "ipm.group.update"]'::jsonb
    ),
    (
      '01a179e8-9237-7c08-bb22-72457e162873',
      'ipm.serviceaccountViewer',
      'Leitura de service accounts em ipm.serviceaccount.',
      '["ipm.serviceaccount.get", "ipm.serviceaccount.list"]'::jsonb
    ),
    (
      '01a179e8-923a-7a7e-a13b-c12f9a41caeb',
      'ipm.serviceaccountAdmin',
      'Administração de service accounts em ipm.serviceaccount.',
      '["ipm.serviceaccount.bind", "ipm.serviceaccount.create", "ipm.serviceaccount.delete", "ipm.serviceaccount.get", "ipm.serviceaccount.list", "ipm.serviceaccount.update"]'::jsonb
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
      'roleType', 'predefined',
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
  ON CONFLICT DO NOTHING
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
      'roleType', i.desired -> 'roleType',
      'description', i.desired -> 'description',
      'permissions', i.desired -> 'permissions',
      'deletionProtection', true
    )
  )
FROM inserted i
ON CONFLICT (message_id) DO NOTHING;

-- Privilégios (docs/data/POSTGRESQL.md §14.2).
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
