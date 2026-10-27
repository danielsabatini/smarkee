-- ipm.permission: API síncrona (decisão 0098) e Controller (decisão 0096).
-- A admissão passa a ser feita na requisição pelo papel `ipm_permission_api`, que substitui
-- `..._manager` e `..._receiver`; o Controller (`ipm_permission_controller`) substitui Observer,
-- Reconciler e Executor. Fim da Operation (tabela, view e privilégios) e do resultado de ação; a
-- causa da geração (`requested_by` e `correlation_id`) passa a ser do próprio recurso; a
-- idempotência do cliente ganha tabela própria.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`, depois de `ipm.sql` (que cria os
-- papéis `ipm_permission_api` e `ipm_permission_controller`). Idempotente: pode ser reaplicada.

ALTER TABLE ipm.permission
  ADD COLUMN IF NOT EXISTS requested_by   text CHECK (length(requested_by) BETWEEN 1 AND 256),
  ADD COLUMN IF NOT EXISTS correlation_id text CHECK (length(correlation_id) BETWEEN 1 AND 256);

-- Recursos anteriores guardam a causa na última Operation da geração vigente.
DO $$
BEGIN
  IF to_regclass('ipm.permission_operation') IS NOT NULL THEN
    UPDATE ipm.permission AS resource
       SET requested_by = operation.requested_by, correlation_id = operation.correlation_id
      FROM (SELECT DISTINCT ON (resource_id) resource_id, requested_by, correlation_id
              FROM ipm.permission_operation
             ORDER BY resource_id, created_at DESC) AS operation
     WHERE operation.resource_id = resource.resource_id AND resource.requested_by IS NULL;
  END IF;
END
$$;

-- Idempotência (`Idempotency-Key`): gravada na transação da admissão, só quando a escrita é aplicada.
CREATE TABLE IF NOT EXISTS ipm.permission_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS permission_idempotency_retention
  ON ipm.permission_idempotency (created_at);

-- A view ganha `observed_generation` (no fim, como exige CREATE OR REPLACE VIEW).
CREATE OR REPLACE VIEW ipm.permission_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at,
         observed_generation
    FROM ipm.permission;

DROP VIEW IF EXISTS ipm.permission_operation_v1;
DROP TABLE IF EXISTS ipm.permission_operation;
DROP TABLE IF EXISTS ipm.permission_action_result;

-- Privilégios: o `api` lê (view), escreve o recurso (sem DELETE: quem remove é o Controller), o
-- outbox e a idempotência. O Controller lê sob lock, grava o observado, apaga o registro quando a
-- remoção converge e insere no outbox. Os papéis antigos perdem tudo do tipo.
GRANT CONNECT ON DATABASE ssot TO ipm_permission_api;
GRANT USAGE ON SCHEMA ipm TO ipm_permission_api;

GRANT SELECT, INSERT, UPDATE ON ipm.permission             TO ipm_permission_api;
GRANT SELECT                 ON ipm.permission_v1          TO ipm_permission_api;
GRANT INSERT                 ON ipm.permission_outbox      TO ipm_permission_api;
GRANT SELECT, INSERT         ON ipm.permission_idempotency TO ipm_permission_api;

GRANT SELECT, DELETE ON ipm.permission_idempotency TO ipm_maintenance;

GRANT CONNECT ON DATABASE ssot TO ipm_permission_controller;
GRANT USAGE ON SCHEMA ipm TO ipm_permission_controller;

GRANT SELECT, UPDATE, DELETE ON ipm.permission        TO ipm_permission_controller;
GRANT INSERT                 ON ipm.permission_outbox TO ipm_permission_controller;

DO $$
DECLARE
  old_role text;
BEGIN
  FOREACH old_role IN ARRAY ARRAY['manager', 'receiver', 'reconciler', 'observer', 'executor']
  LOOP
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ipm_permission_' || old_role) THEN
      EXECUTE format('REVOKE ALL ON ipm.permission, ipm.permission_v1, ipm.permission_outbox FROM %I',
                     'ipm_permission_' || old_role);
      EXECUTE format('REVOKE ALL ON SCHEMA ipm FROM %I', 'ipm_permission_' || old_role);
      EXECUTE format('REVOKE CONNECT ON DATABASE ssot FROM %I', 'ipm_permission_' || old_role);
    END IF;
  END LOOP;
END
$$;
