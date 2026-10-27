-- core.account: API síncrona e Controller (decisões 0096 e 0098). A admissão passa a ser feita na
-- requisição pelo papel `core_account_api`, que substitui `..._manager` e `..._receiver`; a
-- reconciliação passa ao papel `core_account_controller`, que substitui Observer, Reconciler e
-- Executor.
-- Fim da Operation (tabela, view e privilégios) e do `account_action_result`; a causa da geração
-- (`requested_by` e `correlation_id`) passa a ser do próprio recurso; a idempotência do cliente
-- ganha tabela própria.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`, depois de `core.sql` (que cria
-- os papéis `core_account_api` e `core_account_controller`). Idempotente: pode ser reaplicada.

ALTER TABLE core.account
  ADD COLUMN IF NOT EXISTS requested_by   text CHECK (length(requested_by) BETWEEN 1 AND 256),
  ADD COLUMN IF NOT EXISTS correlation_id text CHECK (length(correlation_id) BETWEEN 1 AND 256);

-- Recursos anteriores guardam a causa na última Operation da geração vigente.
DO $$
BEGIN
  IF to_regclass('core.account_operation') IS NOT NULL THEN
    UPDATE core.account AS resource
       SET requested_by = operation.requested_by, correlation_id = operation.correlation_id
      FROM (SELECT DISTINCT ON (resource_id) resource_id, requested_by, correlation_id
              FROM core.account_operation
             ORDER BY resource_id, created_at DESC) AS operation
     WHERE operation.resource_id = resource.resource_id AND resource.requested_by IS NULL;
  END IF;
END
$$;

-- Idempotência (`Idempotency-Key`): gravada na transação da admissão, só quando a escrita é aplicada.
-- O auto-cadastro anônimo não usa chave.
CREATE TABLE IF NOT EXISTS core.account_idempotency (
  requested_by    text        NOT NULL CHECK (length(requested_by) BETWEEN 1 AND 256),
  idempotency_key text        NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request_digest  text        NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
  resource_id     text        NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (requested_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS account_idempotency_retention
  ON core.account_idempotency (created_at);

-- A view ganha `observed_generation` (no fim, como exige CREATE OR REPLACE VIEW).
CREATE OR REPLACE VIEW core.account_v1 AS
  SELECT resource_id, schema_version, lifecycle, reconciliation, desired, desired_generation,
         resource_version, observed, presence, observed_at, phase, conditions, created_at, updated_at,
         observed_generation
    FROM core.account;

DROP VIEW IF EXISTS core.account_operation_v1;
DROP TABLE IF EXISTS core.account_operation;
DROP TABLE IF EXISTS core.account_action_result;

-- Privilégios: o `api` lê (view), escreve o recurso (sem DELETE: quem remove é o Controller, ao
-- convergir), o outbox e a idempotência. O `controller` lê e atualiza o recurso, remove-o ao
-- convergir a exclusão e grava no outbox; não cria nem altera o `desired` de um pedido.
GRANT CONNECT ON DATABASE ssot TO core_account_api, core_account_controller;
GRANT USAGE ON SCHEMA core TO core_account_api, core_account_controller;

GRANT SELECT, INSERT, UPDATE ON core.account             TO core_account_api;
GRANT SELECT                 ON core.account_v1          TO core_account_api;
GRANT INSERT                 ON core.account_outbox      TO core_account_api;
GRANT SELECT, INSERT         ON core.account_idempotency TO core_account_api;

GRANT SELECT, UPDATE, DELETE ON core.account        TO core_account_controller;
GRANT INSERT                 ON core.account_outbox TO core_account_controller;

GRANT SELECT, DELETE ON core.account_idempotency TO core_maintenance;

-- Os papéis antigos perdem tudo do tipo.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'core_account_manager') THEN
    REVOKE ALL ON core.account, core.account_v1, core.account_outbox FROM core_account_manager;
    REVOKE ALL ON SCHEMA core FROM core_account_manager;
    REVOKE CONNECT ON DATABASE ssot FROM core_account_manager;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'core_account_receiver') THEN
    REVOKE ALL ON core.account_v1 FROM core_account_receiver;
    REVOKE ALL ON SCHEMA core FROM core_account_receiver;
    REVOKE CONNECT ON DATABASE ssot FROM core_account_receiver;
  END IF;
END
$$;
