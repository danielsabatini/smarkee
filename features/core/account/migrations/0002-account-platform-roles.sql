-- Migração 0002 de core.account: `desired.platformRoles` (decisão 0025).
-- Projeto: core-account-manager. Executada pela infraestrutura como o dono `smarkee`.
-- Preenche, nas linhas criadas antes da decisão 0025, o conjunto de roles que o usuário
-- cadastrado já recebia (`platformAccess = granted`); `revoked` fica com a lista vazia.
-- Só o jsonb muda: sem coluna nova, sem nova geração. Idempotente: não altera linha que já tem o campo.

UPDATE core.account
   SET desired = desired || jsonb_build_object(
         'platformRoles',
         CASE desired ->> 'platformAccess'
           WHEN 'granted' THEN '["organization.create", "organization.delete", "organization.get", "organization.list", "organization.update", "account.delete", "account.get"]'::jsonb
           ELSE '[]'::jsonb
         END)
 WHERE NOT desired ? 'platformRoles'
   AND NOT desired ? 'platformPermissions';
