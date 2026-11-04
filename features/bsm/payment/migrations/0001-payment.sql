-- Migração 0001 de bsm.payment: método de pagamento da Customer Account no SSOT
-- (docs/data/POSTGRESQL.md §6 e §14.2, decisões 0004, 0055, 0072, 0096 e 0098).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/bsm.sql.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS bsm;

CREATE TABLE IF NOT EXISTS bsm.payment (
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
  requested_by        text        CHECK (requested_by IS NULL OR length(requested_by) BETWEEN 1 AND 256),
  correlation_id      text        CHECK (correlation_id IS NULL OR length(correlation_id) BETWEEN 1 AND 256),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CHECK ((presence IS NULL) = (observed_at IS NULL)),
  CONSTRAINT payment_observed_generation_check
    CHECK (observed_generation IS NULL
           OR (observed_generation >= 1 AND observed_generation <= desired_generation))
);

CREATE INDEX IF NOT EXISTS payment_owner_display_name
  ON bsm.payment ((desired ->> 'ownerAccountId'), (desired ->> 'displayName'));

CREATE TABLE IF NOT EXISTS bsm.payment_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  traceparent  text        CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS payment_outbox_pending
  ON bsm.payment_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS payment_outbox_published
  ON bsm.payment_outbox (published_at) WHERE published_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS bsm.payment_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS payment_idempotency_retention
  ON bsm.payment_idempotency (created_at);

-- Interface de leitura versionada da API (decisão 0004): sem failure_count.
DROP VIEW IF EXISTS bsm.payment_v1;
CREATE VIEW bsm.payment_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed_generation, observed, presence, observed_at, phase, conditions,
         created_at, updated_at
    FROM bsm.payment;

-- Privilégios (docs/data/POSTGRESQL.md §14.2, decisões 0096 e 0098).
GRANT CONNECT ON DATABASE ssot
  TO bsm_payment_api, bsm_payment_publisher, bsm_payment_controller, bsm_maintenance;

REVOKE ALL ON SCHEMA bsm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA bsm FROM PUBLIC;
GRANT USAGE ON SCHEMA bsm
  TO bsm_payment_api, bsm_payment_publisher, bsm_payment_controller, bsm_maintenance;

GRANT SELECT ON bsm.payment_v1 TO bsm_payment_api;
GRANT SELECT, INSERT ON bsm.payment TO bsm_payment_api;
GRANT UPDATE (lifecycle, reconciliation, desired, desired_generation, failure_count,
              phase, requested_by, correlation_id, resource_version, updated_at)
  ON bsm.payment TO bsm_payment_api;
GRANT INSERT ON bsm.payment_outbox TO bsm_payment_api;
GRANT SELECT, INSERT ON bsm.payment_idempotency TO bsm_payment_api;

GRANT SELECT ON bsm.payment_outbox TO bsm_payment_publisher;
GRANT UPDATE (published_at) ON bsm.payment_outbox TO bsm_payment_publisher;

GRANT SELECT, UPDATE, DELETE ON bsm.payment TO bsm_payment_controller;
GRANT INSERT ON bsm.payment_outbox TO bsm_payment_controller;

GRANT SELECT, DELETE
  ON bsm.payment_outbox, bsm.payment_idempotency
  TO bsm_maintenance;
