-- Migração 0009 de cam.account: renomeia `platformRoles` para `platformPermissions` em `desired` e
-- `observed` (docs/identity/PERMISSION.md).
-- Projeto: cam-account-manager. Executada pela infraestrutura como o dono `ssot`.
-- Só o jsonb muda: sem coluna nova, sem nova geração. Idempotente: não altera linhas já migradas.

UPDATE cam.account
   SET desired = (desired - 'platformRoles') || jsonb_build_object('platformPermissions', desired -> 'platformRoles')
 WHERE desired ? 'platformRoles';

UPDATE cam.account
   SET observed = (observed - 'platformRoles') || jsonb_build_object('platformPermissions', observed -> 'platformRoles')
 WHERE observed IS NOT NULL
   AND observed ? 'platformRoles';
