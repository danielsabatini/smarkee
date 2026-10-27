-- Migração 0006 de ipm.user: o `desired` guarda só a intenção (decisão 0097).
-- `permissions` (e o antigo `directPermissions`) saem do `desired`: as permissões efetivas são
-- calculadas pelo Controller a partir do catálogo e ficam em `observed.effectivePermissions`.
-- O `observed` antigo não tem `effectivePermissions`; o Controller o preenche na próxima
-- reconciliação. O `desired_generation` e as Operations não mudam.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

UPDATE ipm.user
   SET desired = desired - 'permissions' - 'directPermissions'
 WHERE desired ? 'permissions' OR desired ? 'directPermissions';
