-- Migração 0003 de ipm.organization: contexto de trace no outbox (decisão 0055).
-- Aditiva e idempotente. O `traceparent` W3C (versão 00) da requisição ou da mensagem que originou a
-- linha fica ao lado da mensagem, e não dentro do envelope: o Publisher o repassa como header NATS.
-- Nulo quando a origem não trouxe contexto (por exemplo, o ciclo de observação).

ALTER TABLE ipm.organization_outbox
  ADD COLUMN IF NOT EXISTS traceparent text
  CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$');
