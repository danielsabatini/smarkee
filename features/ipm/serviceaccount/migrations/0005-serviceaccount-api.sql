-- ipm.serviceaccount: API síncrona (decisão 0098). A admissão passa a ser feita na requisição pelo
-- papel `ipm_serviceaccount_api`, que substitui `..._manager` e `..._receiver`.
-- Fim da Operation (tabela, view e privilégios); a causa da geração (`requested_by` e
-- `correlation_id`) passa a ser do próprio recurso; a idempotência do cliente ganha tabela própria.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`, depois de `ipm.sql` (que cria o
-- papel `ipm_serviceaccount_api`). Idempotente: pode ser reaplicada sem erro.

ALTER TABLE ipm.serviceaccount
  ADD COLUMN IF NOT EXISTS requested_by   text CHECK (length(requested_by) BETWEEN 1 AND 256),
  ADD COLUMN IF NOT EXISTS correlation_id text CHECK (length(correlation_id) BETWEEN 1 AND 256);

-- Recursos anteriores guardam a causa na última Operation da geração vigente.
DO $$
BEGIN
  IF to_regclass('ipm.serviceaccount_operation') IS NOT NULL THEN
    UPDATE ipm.serviceaccount AS resource
       SET requested_by = operation.requested_by, correlation_id = operation.correlation_id
      FROM (SELECT DISTINCT ON (resource_id) resource_id, requested_by, correlation_id
              FROM ipm.serviceaccount_operation
             ORDER BY resource_id, created_at DESC) AS operation
     WHERE operation.resource_id = resource.resource_id AND resource.requested_by IS NULL;
  END IF;
END
$$;

-- Idempotência (`Idempotency-Key`): gravada na transação da admissão, só quando a escrita é aplicada.
CREATE TABLE IF NOT EXISTS ipm.serviceaccount_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS serviceaccount_idempotency_retention
  ON ipm.serviceaccount_idempotency (created_at);

-- A view ganha `observed_generation` (no fim, como exige CREATE OR REPLACE VIEW).
CREATE OR REPLACE VIEW ipm.serviceaccount_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at,
         observed_generation
    FROM ipm.serviceaccount;

DROP VIEW IF EXISTS ipm.serviceaccount_operation_v1;
DROP TABLE IF EXISTS ipm.serviceaccount_operation;

-- Privilégios: o `api` lê (view), escreve o recurso (sem DELETE, decisão 0096), o outbox e a
-- idempotência. Os papéis antigos perdem tudo do tipo.
GRANT CONNECT ON DATABASE ssot TO ipm_serviceaccount_api;
GRANT USAGE ON SCHEMA ipm TO ipm_serviceaccount_api;

GRANT SELECT, INSERT, UPDATE ON ipm.serviceaccount             TO ipm_serviceaccount_api;
GRANT SELECT                 ON ipm.serviceaccount_v1          TO ipm_serviceaccount_api;
GRANT INSERT                 ON ipm.serviceaccount_outbox      TO ipm_serviceaccount_api;
GRANT SELECT, INSERT         ON ipm.serviceaccount_idempotency TO ipm_serviceaccount_api;

GRANT SELECT, DELETE ON ipm.serviceaccount_idempotency TO ipm_maintenance;

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ipm_serviceaccount_manager') THEN
    REVOKE ALL ON ipm.serviceaccount, ipm.serviceaccount_v1, ipm.serviceaccount_outbox
      FROM ipm_serviceaccount_manager;
    REVOKE ALL ON SCHEMA ipm FROM ipm_serviceaccount_manager;
    REVOKE CONNECT ON DATABASE ssot FROM ipm_serviceaccount_manager;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ipm_serviceaccount_receiver') THEN
    REVOKE ALL ON ipm.serviceaccount_v1 FROM ipm_serviceaccount_receiver;
    REVOKE ALL ON SCHEMA ipm FROM ipm_serviceaccount_receiver;
    REVOKE CONNECT ON DATABASE ssot FROM ipm_serviceaccount_receiver;
  END IF;
END
$$;
