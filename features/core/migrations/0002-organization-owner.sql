-- Migração 0002 do módulo core: índice por dono da Organization (decisão 0010).
-- A cota de criação por dono é conferida pelo Manager contando as Organizations de um mesmo
-- `ownerUserId`; o índice evita varrer a tabela. Executada como o dono `smarkee`; idempotente.

CREATE INDEX IF NOT EXISTS organization_owner
  ON core.organization ((desired ->> 'ownerUserId'));
