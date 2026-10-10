-- Migração 0003 do módulo core: User no SSOT (docs/POSTGRESQL.md §6 e §14.2; decisão 0014).
-- Executada pela infraestrutura como o dono `smarkee`, no banco `smarkee`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/core.sql.
-- `user` é palavra reservada do PostgreSQL: a tabela do tipo é sempre citada como core."user".
-- Idempotente: pode ser reaplicada sem erro.

CREATE TABLE IF NOT EXISTS core."user" (
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

CREATE TABLE IF NOT EXISTS core.user_operation (
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
CREATE INDEX IF NOT EXISTS user_operation_resource
  ON core.user_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS user_operation_retention
  ON core.user_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE IF NOT EXISTS core.user_action_result (
  action_id          text        PRIMARY KEY CHECK (length(action_id) BETWEEN 1 AND 512),
  resource_id        text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  action_outcome     text        NOT NULL CHECK (action_outcome IN ('completed', 'failed')),
  recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_action_result_recorded
  ON core.user_action_result (recorded_at);

CREATE TABLE IF NOT EXISTS core.user_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS user_outbox_pending
  ON core.user_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS user_outbox_published
  ON core.user_outbox (published_at) WHERE published_at IS NOT NULL;

-- Interface de leitura versionada da API (decisão 0004): sem failure_count nem requested_by.
CREATE OR REPLACE VIEW core.user_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM core."user";

CREATE OR REPLACE VIEW core.user_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at
    FROM core.user_operation;

-- Privilégios (docs/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE smarkee TO core_user_manager, core_user_api;
GRANT USAGE ON SCHEMA core TO core_user_manager, core_user_api;

REVOKE ALL ON core."user", core.user_operation, core.user_action_result, core.user_outbox FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE, DELETE ON core."user"                TO core_user_manager;
GRANT SELECT, INSERT, UPDATE         ON core.user_operation        TO core_user_manager;
GRANT SELECT, INSERT                 ON core.user_action_result    TO core_user_manager;
GRANT INSERT                         ON core.user_outbox           TO core_user_manager;

GRANT SELECT ON core.user_v1, core.user_operation_v1 TO core_user_api;

GRANT SELECT ON core.user_outbox TO core_relay;
GRANT UPDATE (published_at) ON core.user_outbox TO core_relay;

GRANT SELECT, DELETE
  ON core.user_outbox, core.user_action_result, core.user_operation
  TO core_maintenance;
