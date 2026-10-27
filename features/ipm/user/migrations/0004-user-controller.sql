-- Migração de ipm.user: privilégios do Controller (decisão 0096).
-- O Controller substitui Observer, Reconciler e Executor: lê o recurso sob lock, grava o estado
-- observado, a fase, as conditions e as Operations, apaga o registro quando a remoção converge e
-- grava `desired` suspenso e `updated` no outbox na mesma transação. Não cria nem altera o `desired`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.
-- O papel é criado por infrastructure/dev/database/bootstrap/ipm.sql.

GRANT CONNECT ON DATABASE ssot TO ipm_user_controller;
GRANT USAGE ON SCHEMA ipm TO ipm_user_controller;

GRANT SELECT, UPDATE, DELETE ON ipm.user           TO ipm_user_controller;
GRANT SELECT, UPDATE         ON ipm.user_operation TO ipm_user_controller;
GRANT INSERT                 ON ipm.user_outbox    TO ipm_user_controller;
