-- bsm.account: API síncrona (decisão 0098) e fim dos papéis assíncronos do loop antigo (S6.1).
-- A admissão passa a ser feita na requisição pelo papel `bsm_account_api`, que substitui
-- `..._manager` e `..._receiver`. Fim da Operation (tabela, view e privilégios) e do resultado de
-- ação (o tipo não tem Executor externo); a causa da geração (`requested_by` e `correlation_id`) passa a
-- ser do próprio recurso; a idempotência do cliente ganha tabela própria.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`, depois de `bsm.sql` (que cria o
-- papel `bsm_account_api`). Idempotente: pode ser reaplicada sem erro.

ALTER TABLE bsm.account
  ADD COLUMN IF NOT EXISTS requested_by   text CHECK (length(requested_by) BETWEEN 1 AND 256),
  ADD COLUMN IF NOT EXISTS correlation_id text CHECK (length(correlation_id) BETWEEN 1 AND 256);

-- Recursos anteriores guardam a causa na última Operation da geração vigente.
DO $$
BEGIN
  IF to_regclass('bsm.account_operation') IS NOT NULL THEN
    UPDATE bsm.account AS resource
       SET requested_by = operation.requested_by, correlation_id = operation.correlation_id
      FROM (SELECT DISTINCT ON (resource_id) resource_id, requested_by, correlation_id
              FROM bsm.account_operation
             ORDER BY resource_id, created_at DESC) AS operation
     WHERE operation.resource_id = resource.resource_id AND resource.requested_by IS NULL;
  END IF;
END
$$;

-- A Billing Account é gerida no SSOT: sem Observer/Executor externo, toda conta existente já está convergida. As linhas
-- anteriores passam a `Ready` com `observed_generation = generation`.
UPDATE bsm.account
   SET phase = 'Ready', observed_generation = desired_generation
 WHERE phase <> 'Ready' OR observed_generation IS DISTINCT FROM desired_generation;

-- Idempotência (`Idempotency-Key`): gravada na transação da admissão, só quando a escrita é aplicada.
CREATE TABLE IF NOT EXISTS bsm.account_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS account_idempotency_retention
  ON bsm.account_idempotency (created_at);

-- A view ganha `observed_generation` (no fim, como exige CREATE OR REPLACE VIEW).
CREATE OR REPLACE VIEW bsm.account_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at,
         observed_generation
    FROM bsm.account;

DROP VIEW IF EXISTS bsm.account_operation_v1;
DROP TABLE IF EXISTS bsm.account_operation;
DROP TABLE IF EXISTS bsm.account_action_result;

-- Privilégios: o `api` lê (view), escreve o recurso (com DELETE: a exclusão remove a linha e o
-- tombstone vai no outbox), o outbox e a idempotência. Os papéis antigos perdem tudo do tipo.
GRANT CONNECT ON DATABASE ssot TO bsm_account_api;
GRANT USAGE ON SCHEMA bsm TO bsm_account_api;

GRANT SELECT, INSERT, UPDATE, DELETE ON bsm.account             TO bsm_account_api;
GRANT SELECT                         ON bsm.account_v1          TO bsm_account_api;
GRANT INSERT                         ON bsm.account_outbox      TO bsm_account_api;
GRANT SELECT, INSERT                 ON bsm.account_idempotency TO bsm_account_api;

GRANT SELECT, DELETE ON bsm.account_idempotency TO bsm_maintenance;

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'bsm_account_manager') THEN
    REVOKE ALL ON bsm.account, bsm.account_v1, bsm.account_outbox FROM bsm_account_manager;
    REVOKE ALL ON SCHEMA bsm FROM bsm_account_manager;
    REVOKE CONNECT ON DATABASE ssot FROM bsm_account_manager;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'bsm_account_receiver') THEN
    REVOKE ALL ON bsm.account_v1 FROM bsm_account_receiver;
    REVOKE ALL ON SCHEMA bsm FROM bsm_account_receiver;
    REVOKE CONNECT ON DATABASE ssot FROM bsm_account_receiver;
  END IF;
END
$$;
