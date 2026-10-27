-- Migração 0001 de ipm.serviceaccount: service account (identidade de máquina) da Organization no
-- SSOT (docs/data/POSTGRESQL.md §6 e §14.2, decisão 0094).
-- Projeto: ipm-serviceaccount-manager (decisão 0015), dono do esquema do tipo.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`; serviços de runtime não
-- executam DDL. Os papéis de função são criados por infrastructure/dev/database/bootstrap/ipm.sql.
-- Nasce com o estado atual das migrações do modelo (ipm/user 0001 a 0003): o motivo de rejeição
-- `protected` (decisão 0043), o `traceparent` do outbox (decisão 0055), a `observed_generation`
-- (decisão 0072) e o status `superseded` da Operation (decisão 0091).
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.serviceaccount (
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
  -- Última geração confirmada por uma observação feita depois dela, como o
  -- `status.observedGeneration` do Kubernetes (decisão 0072).
  observed_generation bigint,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK ((presence IS NULL) = (observed_at IS NULL)),
  CONSTRAINT serviceaccount_observed_generation_check
    CHECK (observed_generation IS NULL
           OR (observed_generation >= 1 AND observed_generation <= desired_generation))
);

CREATE TABLE IF NOT EXISTS ipm.serviceaccount_operation (
  operation_id            text        PRIMARY KEY CHECK (length(operation_id) BETWEEN 1 AND 128),
  resource_id             text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  operation_type          text        NOT NULL CHECK (operation_type IN ('create', 'update', 'delete')),
  desired_generation      bigint      CHECK (desired_generation >= 1),
  requested_by            text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  correlation_id          text        NOT NULL CHECK (length(correlation_id) BETWEEN 1 AND 256),
  request_digest          text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  operation_status        text        NOT NULL
                          CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded')),
  operation_status_reason text        CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found', 'protected')),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  completed_at            timestamptz,
  CHECK ((operation_status = 'rejected') = (operation_status_reason IS NOT NULL)),
  CHECK ((operation_status = 'rejected') = (desired_generation IS NULL))
);
CREATE INDEX IF NOT EXISTS serviceaccount_operation_resource
  ON ipm.serviceaccount_operation (resource_id, created_at);
CREATE INDEX IF NOT EXISTS serviceaccount_operation_retention
  ON ipm.serviceaccount_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');

CREATE TABLE IF NOT EXISTS ipm.serviceaccount_outbox (
  sequence     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   text        NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 128),
  resource_id  text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  subject      text        NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  payload      jsonb       NOT NULL CHECK (pg_column_size(payload) <= 262144),
  -- `traceparent` W3C da origem da linha, repassado pelo Publisher como header (decisão 0055).
  traceparent  text        CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS serviceaccount_outbox_pending
  ON ipm.serviceaccount_outbox (sequence) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS serviceaccount_outbox_published
  ON ipm.serviceaccount_outbox (published_at) WHERE published_at IS NOT NULL;

-- Índice de busca do Manager e do Receiver: a Organization (cota, lista e nome único nela,
-- decisão 0094), conferida na unidade atômica do pedido (docs/data/SSOT.md §10.1).
CREATE INDEX IF NOT EXISTS serviceaccount_organization
  ON ipm.serviceaccount ((desired ->> 'organizationId'), (desired ->> 'name'));

-- Interface de leitura versionada do Receiver (decisão 0004): sem failure_count.
-- DROP VIEW prévio permite reaplicar a migração mesmo após 0005 adicionar observed_generation.
DROP VIEW IF EXISTS ipm.serviceaccount_v1;
CREATE VIEW ipm.serviceaccount_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at
    FROM ipm.serviceaccount;

CREATE OR REPLACE VIEW ipm.serviceaccount_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM ipm.serviceaccount_operation;

-- Privilégios (docs/data/POSTGRESQL.md §14.2).
GRANT CONNECT ON DATABASE ssot
  TO ipm_serviceaccount_manager, ipm_serviceaccount_receiver, ipm_serviceaccount_publisher, ipm_maintenance;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm
  TO ipm_serviceaccount_manager, ipm_serviceaccount_receiver, ipm_serviceaccount_publisher, ipm_maintenance;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.serviceaccount               TO ipm_serviceaccount_manager;
GRANT SELECT, INSERT, UPDATE         ON ipm.serviceaccount_operation     TO ipm_serviceaccount_manager;
GRANT INSERT                         ON ipm.serviceaccount_outbox        TO ipm_serviceaccount_manager;

GRANT SELECT ON ipm.serviceaccount_v1, ipm.serviceaccount_operation_v1 TO ipm_serviceaccount_receiver;

GRANT SELECT ON ipm.serviceaccount_outbox TO ipm_serviceaccount_publisher;
GRANT UPDATE (published_at) ON ipm.serviceaccount_outbox TO ipm_serviceaccount_publisher;

GRANT SELECT, DELETE
  ON ipm.serviceaccount_outbox, ipm.serviceaccount_operation
  TO ipm_maintenance;
