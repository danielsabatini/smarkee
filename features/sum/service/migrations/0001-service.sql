-- Migração 0001 de sum."service": ligação de um serviço por usuário no SSOT (decisão 0033).
-- Projeto: sum-service-manager (decisão 0015), dono do esquema do tipo.
-- Executada pela infraestrutura como o dono `smarkee`, no banco `smarkee`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/sum.sql.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS sum;

-- Uma linha por ligação. A ligação ativa é única por usuário e serviço: o índice parcial impede
-- duas ligações `present` para o mesmo par, mesmo com dois pedidos concorrentes (decisão 0033).
-- As ligações desfeitas (`absent`) continuam existindo, e a nova ligação cria outra linha.
CREATE TABLE IF NOT EXISTS sum.service (
  resource_id        text        PRIMARY KEY
                     CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  schema_version     text        NOT NULL CHECK (schema_version ~ '^[0-9]+\.[0-9]+$'),
  owner_account_id      text        NOT NULL
                     CHECK (owner_account_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  service            text        NOT NULL CHECK (service ~ '^[a-z][a-z0-9]*$' AND length(service) BETWEEN 2 AND 32),
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
  CHECK ((presence IS NULL) = (observed_at IS NULL)),
  CHECK (lifecycle = 'present' OR jsonb_array_length(desired -> 'servicePermissions') = 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS service_active_link
  ON sum.service (owner_account_id, service)
  WHERE lifecycle = 'present';

CREATE TABLE IF NOT EXISTS sum.service_operation (
  operation_id            text        PRIMARY KEY CHECK (length(operation_id) BETWEEN 1 AND 128),
  resource_id             text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  operation_type          text        NOT NULL CHECK (operation_type IN ('create', 'delete')),
  desired_generation      bigint      CHECK (desired_generation >= 1),
  requested_by            text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  correlation_id          text        NOT NULL CHECK (length(correlation_id) BETWEEN 1 AND 256),
  request_digest          text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  operation_status        text        NOT NULL
                          CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected')),
  operation_status_reason text        CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found', 'already_exists', 'service_unavailable')),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  completed_at            timestamptz,
  CHECK ((operation_status = 'rejected') = (operation_status_reason IS NOT NULL)),
  CHECK ((operation_status = 'rejected') = (desired_generation IS NULL))
);
CREATE INDEX IF NOT EXISTS service_operation_resource
  ON sum.service_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS service_operation_retention
  ON sum.service_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected');

CREATE TABLE IF NOT EXISTS sum.service_action_result (
  action_id          text        PRIMARY KEY CHECK (length(action_id) BETWEEN 1 AND 512),
  resource_id        text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  desired_generation bigint      NOT NULL CHECK (desired_generation >= 1),
  action_outcome     text        NOT NULL CHECK (action_outcome IN ('completed', 'failed')),
  recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS service_action_result_recorded
  ON sum.service_action_result (recorded_at);

CREATE TABLE IF NOT EXISTS sum.service_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS service_outbox_pending
  ON sum.service_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS service_outbox_published
  ON sum.service_outbox (published_at) WHERE published_at IS NOT NULL;

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count.
CREATE OR REPLACE VIEW sum.service_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM sum.service;

-- `requested_by` aparece só na view da Operation, para o Receiver autorizar a leitura.
CREATE OR REPLACE VIEW sum.service_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM sum.service_operation;

-- Privilégios (docs/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE smarkee
  TO sum_service_manager, sum_service_receiver, sum_service_publisher, sum_service_maintenance;

REVOKE ALL ON SCHEMA sum FROM PUBLIC;
GRANT USAGE ON SCHEMA sum
  TO sum_service_manager, sum_service_receiver, sum_service_publisher, sum_service_maintenance;

REVOKE ALL ON sum.service, sum.service_operation, sum.service_action_result, sum.service_outbox FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE, DELETE ON sum.service              TO sum_service_manager;
GRANT SELECT, INSERT, UPDATE         ON sum.service_operation    TO sum_service_manager;
GRANT SELECT, INSERT                 ON sum.service_action_result TO sum_service_manager;
GRANT INSERT                         ON sum.service_outbox       TO sum_service_manager;

GRANT SELECT ON sum.service_v1, sum.service_operation_v1 TO sum_service_receiver;

GRANT SELECT ON sum.service_outbox TO sum_service_publisher;
GRANT UPDATE (published_at) ON sum.service_outbox TO sum_service_publisher;

GRANT SELECT, DELETE
  ON sum.service_outbox, sum.service_action_result, sum.service_operation
  TO sum_service_maintenance;
