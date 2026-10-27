-- Migração 0004 de ipm.serviceaccount: o `desired` guarda só a intenção (decisão 0097).
-- `permissions` sai do `desired`: as permissões efetivas são calculadas pelo Controller a partir
-- do catálogo e ficam em `observed.effectivePermissions`. O `observed` antigo não tem
-- `effectivePermissions`; o Controller o preenche na próxima reconciliação. O `desired_generation`
-- e as Operations não mudam.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

UPDATE ipm.serviceaccount
   SET desired = desired - 'permissions'
 WHERE desired ? 'permissions';
