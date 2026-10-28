-- sum.service: API síncrona e Controller (decisões 0096 e 0098). A admissão passa a ser feita na
-- requisição pelo papel `sum_service_api`, que substitui `..._manager` e `..._receiver`; a
-- reconciliação passa ao papel `sum_service_controller`, que substitui Observer, Reconciler e
-- Executor.
-- Fim da Operation (tabela, view e privilégios) e do `service_action_result`; a causa da geração
-- (`requested_by` e `correlation_id`) passa a ser do próprio recurso; a idempotência do cliente
-- ganha tabela própria.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`, depois de `sum.sql` (que cria
-- os papéis `sum_service_api` e `sum_service_controller`). Idempotente: pode ser reaplicada.

ALTER TABLE sum.service
  ADD COLUMN IF NOT EXISTS requested_by   text CHECK (length(requested_by) BETWEEN 1 AND 256),
  ADD COLUMN IF NOT EXISTS correlation_id text CHECK (length(correlation_id) BETWEEN 1 AND 256);

-- Recursos anteriores guardam a causa na última Operation da geração vigente.
DO $$
BEGIN
  IF to_regclass('sum.service_operation') IS NOT NULL THEN
    UPDATE sum.service AS resource
       SET requested_by = operation.requested_by, correlation_id = operation.correlation_id
      FROM (SELECT DISTINCT ON (resource_id) resource_id, requested_by, correlation_id
              FROM sum.service_operation
             ORDER BY resource_id, created_at DESC) AS operation
     WHERE operation.resource_id = resource.resource_id AND resource.requested_by IS NULL;
  END IF;
END
$$;

-- Idempotência (`Idempotency-Key`): gravada na transação da admissão, só quando a escrita é aplicada.
CREATE TABLE IF NOT EXISTS sum.service_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS service_idempotency_retention
  ON sum.service_idempotency (created_at);

-- A view ganha `observed_generation` (no fim, como exige CREATE OR REPLACE VIEW).
CREATE OR REPLACE VIEW sum.service_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at,
         observed_generation
    FROM sum.service;

DROP VIEW IF EXISTS sum.service_operation_v1;
DROP TABLE IF EXISTS sum.service_operation;
DROP TABLE IF EXISTS sum.service_action_result;

-- Privilégios: o `api` lê (view), escreve o recurso (sem DELETE), o outbox e a idempotência. O
-- `controller` lê e atualiza o recurso, grava no outbox e remove as ligações de uma conta removida
-- (decisão 0044); o desligamento é `lifecycle = 'absent'` e não apaga a ligação (decisão 0033).
GRANT CONNECT ON DATABASE ssot TO sum_service_api, sum_service_controller;
GRANT USAGE ON SCHEMA sum TO sum_service_api, sum_service_controller;

GRANT SELECT, INSERT, UPDATE ON sum.service             TO sum_service_api;
GRANT SELECT                 ON sum.service_v1          TO sum_service_api;
GRANT INSERT                 ON sum.service_outbox      TO sum_service_api;
GRANT SELECT, INSERT         ON sum.service_idempotency TO sum_service_api;

GRANT SELECT, UPDATE, DELETE ON sum.service        TO sum_service_controller;
GRANT INSERT                 ON sum.service_outbox TO sum_service_controller;

GRANT SELECT, DELETE ON sum.service_idempotency TO sum_service_maintenance;

-- Os papéis antigos perdem tudo do tipo.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'sum_service_manager') THEN
    REVOKE ALL ON sum.service, sum.service_v1, sum.service_outbox FROM sum_service_manager;
    REVOKE ALL ON SCHEMA sum FROM sum_service_manager;
    REVOKE CONNECT ON DATABASE ssot FROM sum_service_manager;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'sum_service_receiver') THEN
    REVOKE ALL ON sum.service_v1 FROM sum_service_receiver;
    REVOKE ALL ON SCHEMA sum FROM sum_service_receiver;
    REVOKE CONNECT ON DATABASE ssot FROM sum_service_receiver;
  END IF;
END
$$;
