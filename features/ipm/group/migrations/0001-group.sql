-- Migração 0001 de ipm.group: Grupo de usuários da Organization no SSOT da Smarkee (docs/data/POSTGRESQL.md §6 e §14.2; decisões 0085 e 0088).
-- Projeto: ipm-group-manager (decisões 0015 e 0088), dono do esquema do tipo.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/ipm.sql.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.group (
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
  CONSTRAINT group_observed_generation_check
    CHECK (observed_generation IS NULL
           OR (observed_generation >= 1 AND observed_generation <= desired_generation))
);

CREATE TABLE IF NOT EXISTS ipm.group_operation (
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
CREATE INDEX IF NOT EXISTS group_operation_resource
  ON ipm.group_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS group_operation_retention
  ON ipm.group_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE IF NOT EXISTS ipm.group_action_result (
  action_id          text        PRIMARY KEY CHECK (length(action_id) BETWEEN 1 AND 512),
  resource_id        text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  action_outcome     text        NOT NULL CHECK (action_outcome IN ('completed', 'failed')),
  recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS group_action_result_recorded
  ON ipm.group_action_result (recorded_at);

CREATE TABLE IF NOT EXISTS ipm.group_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  traceparent  text        CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS group_outbox_pending
  ON ipm.group_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS group_outbox_published
  ON ipm.group_outbox (published_at) WHERE published_at IS NOT NULL;

-- Índice de unicidade de `name` por `organizationId` entre grupos ativos (`lifecycle = 'present'`),
-- conferido na unidade atômica do pedido sob advisory lock (docs/data/SSOT.md §10.1; decisões 0085 e 0088).
CREATE UNIQUE INDEX IF NOT EXISTS group_active_organization_name
  ON ipm.group ((desired ->> 'organizationId'), (desired ->> 'name'))
  WHERE lifecycle = 'present';

-- Índice de busca por organizationId (para contagem de cota e listagem de grupos da Organization)
CREATE INDEX IF NOT EXISTS group_organization_id
  ON ipm.group ((desired ->> 'organizationId'))
  WHERE lifecycle = 'present';

-- Interface de leitura do Receiver (docs/data/POSTGRESQL.md §14.2): views sem colunas internas de auditoria.
CREATE OR REPLACE VIEW ipm.group_v1 AS
  SELECT
    resource_id,
    schema_version,
    resource_version,
    desired_generation,
    lifecycle,
    reconciliation,
    phase,
    conditions,
    desired,
    observed,
    presence,
    observed_at,
    created_at,
    updated_at
  FROM ipm.group;

CREATE OR REPLACE VIEW ipm.group_operation_v1 AS
  SELECT
    operation_id,
    resource_id,
    operation_type,
    desired_generation,
    request_digest,
    operation_status,
    operation_status_reason,
    requested_by,
    created_at,
    updated_at,
    completed_at
  FROM ipm.group_operation;

-- Concessão de privilégios aos papéis de função do SSOT (decisões 0015 e 0088).
REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ipm FROM PUBLIC;

GRANT USAGE ON SCHEMA ipm TO ipm_group_manager, ipm_group_receiver, ipm_group_publisher, ipm_maintenance;

GRANT CONNECT ON DATABASE ssot
  TO ipm_group_manager, ipm_group_receiver, ipm_group_publisher, ipm_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.group               TO ipm_group_manager;
GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.group_operation     TO ipm_group_manager;
GRANT SELECT, INSERT                 ON ipm.group_action_result TO ipm_group_manager;
GRANT INSERT                         ON ipm.group_outbox        TO ipm_group_manager;

GRANT SELECT ON ipm.group_v1, ipm.group_operation_v1 TO ipm_group_receiver;

GRANT SELECT ON ipm.group_outbox TO ipm_group_publisher;
GRANT UPDATE (published_at) ON ipm.group_outbox TO ipm_group_publisher;

GRANT SELECT, DELETE
  ON ipm.group_outbox, ipm.group_action_result, ipm.group_operation
  TO ipm_maintenance;
