-- Migração 0001 de ipm.organization: Organization no SSOT (docs/data/POSTGRESQL.md §6 e §14.2).
-- Projeto: ipm-organization-manager (decisão 0015), dono do esquema do tipo.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/ipm.sql.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.organization (
  resource_id        text        PRIMARY KEY
                     CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  schema_version     text        NOT NULL CHECK (schema_version ~ '^[0-9]+\.[0-9]+$'),
  lifecycle          text        NOT NULL CHECK (lifecycle IN ('present', 'absent')),
  reconciliation     text        NOT NULL DEFAULT 'active' CHECK (reconciliation IN ('active', 'suspended')),
  desired            jsonb       NOT NULL
                     CHECK (jsonb_typeof(desired) = 'object' AND pg_column_size(desired) <= 262144),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  resource_version   bigint      NOT NULL DEFAULT 1,
  observed           jsonb
                     CHECK (observed IS NULL OR (jsonb_typeof(observed) = 'object' AND pg_column_size(observed) <= 262144)),
  presence           text        CHECK (presence IN ('present', 'absent', 'unknown')),
  observed_at        timestamptz,
  phase              text        NOT NULL CHECK (phase IN ('Pending', 'Reconciling', 'Ready', 'Failed', 'Deleting')),
  conditions         jsonb       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(conditions) = 'array'),
  failure_count      integer     NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK ((presence IS NULL) = (observed_at IS NULL))
);

CREATE TABLE IF NOT EXISTS ipm.organization_operation (
  operation_id            text        PRIMARY KEY CHECK (length(operation_id) BETWEEN 1 AND 128),
  resource_id             text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  operation_type          text        NOT NULL CHECK (operation_type IN ('create', 'update', 'delete')),
  desired_generation      bigint      CHECK (desired_generation >= 1),
  requested_by            text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  correlation_id          text        NOT NULL CHECK (length(correlation_id) BETWEEN 1 AND 256),
  request_digest          text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  operation_status        text        NOT NULL
                          CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected')),
  operation_status_reason text        CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found')),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  completed_at            timestamptz,
  CHECK ((operation_status = 'rejected') = (operation_status_reason IS NOT NULL)),
  CHECK ((operation_status = 'rejected') = (desired_generation IS NULL))
);
CREATE INDEX IF NOT EXISTS organization_operation_resource
  ON ipm.organization_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS organization_operation_retention
  ON ipm.organization_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE IF NOT EXISTS ipm.organization_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS organization_outbox_pending
  ON ipm.organization_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS organization_outbox_published
  ON ipm.organization_outbox (published_at) WHERE published_at IS NOT NULL;

-- Índices de busca do Manager: dono (cota por dono, decisão 0010) e nome (unicidade), conferidos
-- na unidade atômica do pedido (docs/data/SSOT.md §10.1).
CREATE INDEX IF NOT EXISTS organization_owner
  ON ipm.organization ((desired ->> 'ownerAccountId'));
CREATE INDEX IF NOT EXISTS organization_name
  ON ipm.organization ((desired ->> 'name'));

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count. `requested_by` aparece
-- só na view da Operation, para o Receiver autorizar a leitura (docs/data/POSTGRESQL.md §6.5).
CREATE OR REPLACE VIEW ipm.organization_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM ipm.organization;

CREATE OR REPLACE VIEW ipm.organization_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM ipm.organization_operation;

-- Privilégios (docs/data/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE ssot
  TO ipm_organization_manager, ipm_organization_receiver, ipm_organization_publisher, ipm_maintenance;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm
  TO ipm_organization_manager, ipm_organization_receiver, ipm_organization_publisher, ipm_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.organization               TO ipm_organization_manager;
GRANT SELECT, INSERT, UPDATE         ON ipm.organization_operation     TO ipm_organization_manager;
GRANT INSERT                         ON ipm.organization_outbox        TO ipm_organization_manager;

GRANT SELECT ON ipm.organization_v1, ipm.organization_operation_v1 TO ipm_organization_receiver;

GRANT SELECT ON ipm.organization_outbox TO ipm_organization_publisher;
GRANT UPDATE (published_at) ON ipm.organization_outbox TO ipm_organization_publisher;

GRANT SELECT, DELETE
  ON ipm.organization_outbox, ipm.organization_operation
  TO ipm_maintenance;
