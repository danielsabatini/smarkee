-- Migração de ipm.user: fim de `user_action_result` e privilégios mínimos do Manager (decisão 0096).
-- O Controller concentra observação, ação e resultado num ciclo atômico; a idempotência da ação
-- não precisa mais do registro por `actionId`, e o Manager deixa de aplicar `observed` e resultados:
-- só admite pedidos (insere, altera o `desired` e insere Operations e outbox).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

DROP TABLE IF EXISTS ipm.user_action_result;

REVOKE DELETE ON ipm.user FROM ipm_user_manager;
REVOKE UPDATE ON ipm.user_operation FROM ipm_user_manager;
