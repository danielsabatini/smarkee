-- Migração 0002 de sum."service": uma recusa de criação não tem recurso, então `resource_id` da
-- Operation passa a aceitar nulo (decisão 0033). Só afrouxa a restrição: as linhas existentes não mudam.
-- Idempotente: soltar uma restrição que já não existe não falha.

ALTER TABLE sum.service_operation ALTER COLUMN resource_id DROP NOT NULL;
