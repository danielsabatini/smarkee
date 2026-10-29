-- Migração de ipm.serviceaccount: fim de `serviceaccount_action_result` e privilégios mínimos do Manager (decisão 0096).
-- O Controller concentra observação, ação e resultado num ciclo atômico; a idempotência da ação
-- não precisa mais do registro por `actionId`, e o Manager deixa de aplicar `observed` e resultados:
-- só admite pedidos (insere, altera o `desired` e insere Operations e outbox).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

DROP TABLE IF EXISTS ipm.serviceaccount_action_result;

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ipm_serviceaccount_manager') THEN
    REVOKE DELETE ON ipm.serviceaccount FROM ipm_serviceaccount_manager;
    REVOKE UPDATE ON ipm.serviceaccount_operation FROM ipm_serviceaccount_manager;
  END IF;
END
$$;
