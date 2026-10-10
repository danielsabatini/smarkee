-- Migração 0004 do módulo core: índices de busca e `requested_by` na view da Operation.
-- Executada como o dono `smarkee`; idempotente.
--
-- Índices: o Manager confere a unicidade do nome da Organization e do e-mail do User na unidade
-- atômica do pedido (docs/SSOT.md §10.1); os índices evitam varrer a tabela.
--
-- View da Operation: a API autoriza a leitura da Operation (somente o solicitante e os
-- operadores, docs/RESOURCE-CONTROL-LOOP.md §6.1.1) e por isso precisa de `requested_by`. A API
-- não o devolve ao cliente. A coluna entra no fim da lista: mudança compatível da view.

CREATE INDEX IF NOT EXISTS organization_name
  ON core.organization ((desired ->> 'name'));

CREATE INDEX IF NOT EXISTS user_email
  ON core."user" ((desired ->> 'email'));

CREATE OR REPLACE VIEW core.organization_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM core.organization_operation;

CREATE OR REPLACE VIEW core.user_operation_v1 AS
  SELECT operation_id, resource_id, operation_type, desired_generation, request_digest,
         operation_status, operation_status_reason, created_at, updated_at, completed_at,
         requested_by
    FROM core.user_operation;
