-- Migração 0012 de core.account: Tickets temporários de rastreamento do cadastro (UUIDv7).
-- Permite que o solicitante acompanhe a ativação da conta sem autenticação prévia
-- e sem expor dados pessoais (PII) nem permitir enumeração pública.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`.
-- Idempotente: pode ser reaplicada sem erro.

CREATE TABLE IF NOT EXISTS core.account_registration_ticket (
  ticket         text        PRIMARY KEY
                 CHECK (ticket ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  resource_id    text        NOT NULL REFERENCES core.account(resource_id) ON DELETE CASCADE,
  email          text        NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  expires_at     timestamptz NOT NULL,
  last_resend_at timestamptz
);

CREATE INDEX IF NOT EXISTS account_registration_ticket_expires
  ON core.account_registration_ticket (expires_at);

CREATE INDEX IF NOT EXISTS account_registration_ticket_email
  ON core.account_registration_ticket (email);

CREATE INDEX IF NOT EXISTS account_registration_ticket_resource
  ON core.account_registration_ticket (resource_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON core.account_registration_ticket TO core_account_api;
GRANT SELECT, DELETE ON core.account_registration_ticket TO core_maintenance;
