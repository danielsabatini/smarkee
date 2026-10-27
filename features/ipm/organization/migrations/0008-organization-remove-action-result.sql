-- Migração de ipm.organization: fim de `organization_action_result` e privilégios mínimos do Manager (decisão 0096).
-- O Controller concentra observação, ação e resultado num ciclo atômico; a idempotência da ação
-- não precisa mais do registro por `actionId`, e o Manager deixa de aplicar `observed` e resultados:
-- só admite pedidos (insere, altera o `desired` e insere Operations e outbox).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

DROP TABLE IF EXISTS ipm.organization_action_result;

REVOKE DELETE ON ipm.organization FROM ipm_organization_manager;
REVOKE UPDATE ON ipm.organization_operation FROM ipm_organization_manager;
