-- ipm.role: API síncrona (decisão 0098) e fim do plano de dados `platform` (S4).
-- A admissão passa a ser feita na requisição pelo papel `ipm_role_api`, que substitui
-- `..._manager` e `..._receiver`. Fim da Operation (tabela, view e privilégios) e do resultado de
-- ação (o tipo não tem Executor); a causa da geração (`requested_by` e `correlation_id`) passa a
-- ser do próprio recurso; a idempotência do cliente ganha tabela própria.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`, depois de `ipm.sql` (que cria o
-- papel `ipm_role_api`). Idempotente: pode ser reaplicada sem erro.

ALTER TABLE ipm.role
  ADD COLUMN IF NOT EXISTS requested_by   text CHECK (length(requested_by) BETWEEN 1 AND 256),
  ADD COLUMN IF NOT EXISTS correlation_id text CHECK (length(correlation_id) BETWEEN 1 AND 256);

-- Recursos anteriores guardam a causa na última Operation da geração vigente.
DO $$
BEGIN
  IF to_regclass('ipm.role_operation') IS NOT NULL THEN
    UPDATE ipm.role AS resource
       SET requested_by = operation.requested_by, correlation_id = operation.correlation_id
      FROM (SELECT DISTINCT ON (resource_id) resource_id, requested_by, correlation_id
              FROM ipm.role_operation
             ORDER BY resource_id, created_at DESC) AS operation
     WHERE operation.resource_id = resource.resource_id AND resource.requested_by IS NULL;
  END IF;
END
$$;

-- A Role é só dado do SSOT: sem Observer, toda Role existente já está convergida. As linhas
-- anteriores (inclusive as predefinidas) passam a `Ready` com `observed_generation = generation`.
UPDATE ipm.role
   SET phase = 'Ready', observed_generation = desired_generation
 WHERE phase <> 'Ready' OR observed_generation IS DISTINCT FROM desired_generation;

-- Idempotência (`Idempotency-Key`): gravada na transação da admissão, só quando a escrita é aplicada.
CREATE TABLE IF NOT EXISTS ipm.role_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS role_idempotency_retention
  ON ipm.role_idempotency (created_at);

-- A view ganha `observed_generation` (no fim, como exige CREATE OR REPLACE VIEW).
CREATE OR REPLACE VIEW ipm.role_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at,
         observed_generation
    FROM ipm.role;

DROP VIEW IF EXISTS ipm.role_operation_v1;
DROP TABLE IF EXISTS ipm.role_operation;
DROP TABLE IF EXISTS ipm.role_action_result;

-- Privilégios: o `api` lê (view), escreve o recurso (com DELETE: a exclusão remove a linha e o
-- tombstone vai no outbox), o outbox e a idempotência. Os papéis antigos perdem tudo do tipo.
GRANT CONNECT ON DATABASE ssot TO ipm_role_api;
GRANT USAGE ON SCHEMA ipm TO ipm_role_api;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.role             TO ipm_role_api;
GRANT SELECT                         ON ipm.role_v1          TO ipm_role_api;
GRANT INSERT                         ON ipm.role_outbox      TO ipm_role_api;
GRANT SELECT, INSERT                 ON ipm.role_idempotency TO ipm_role_api;

GRANT SELECT, DELETE ON ipm.role_idempotency TO ipm_maintenance;

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ipm_role_manager') THEN
    REVOKE ALL ON ipm.role, ipm.role_v1, ipm.role_outbox FROM ipm_role_manager;
    REVOKE ALL ON SCHEMA ipm FROM ipm_role_manager;
    REVOKE CONNECT ON DATABASE ssot FROM ipm_role_manager;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ipm_role_receiver') THEN
    REVOKE ALL ON ipm.role_v1 FROM ipm_role_receiver;
    REVOKE ALL ON SCHEMA ipm FROM ipm_role_receiver;
    REVOKE CONNECT ON DATABASE ssot FROM ipm_role_receiver;
  END IF;
END
$$;
