-- Migração 0005 de ipm.permission: catálogo de permissões dos módulos de cofre (svm), criptografia (ekm) e PKI (clm) (decisões 0102 e 0103).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente: pode ser reaplicada.

BEGIN;

WITH predefined(resource_id, permission_name, module_group, description, grantable) AS (
  VALUES
    -- svm.secret (roles-svm): segredos no cofre (SVM)
    ('01a1896f-895e-73b9-befc-5b531ddf380d', 'svm.secret.create', 'svm', 'Criar segredos no cofre (SVM)', true),
    ('01a1896f-895e-73b9-befc-5b544c6c3d75', 'svm.secret.delete', 'svm', 'Excluir segredos no cofre (SVM)', true),
    ('01a1896f-895e-73b9-befc-5b554ed83cc9', 'svm.secret.get',    'svm', 'Ler segredos no cofre (SVM)', true),
    ('01a1896f-895e-73b9-befc-5b567ac51c65', 'svm.secret.list',   'svm', 'Listar segredos no cofre (SVM)', true),
    ('01a1896f-895e-73b9-befc-5b5744cbc600', 'svm.secret.update', 'svm', 'Alterar segredos no cofre (SVM)', true),
    ('01a1896f-895e-73b9-befc-5b5817dfc809', 'svm.secret.operate', 'svm', 'Operador: gerenciar qualquer segredo no cofre (SVM)', false),
    -- ekm.key (roles-ekm): chaves de criptografia (EKM)
    ('01a1896f-895e-73b9-befc-5b5964ccd672', 'ekm.key.create', 'ekm', 'Criar chaves de criptografia (EKM)', true),
    ('01a1896f-895e-73b9-befc-5b5a7720b1d1', 'ekm.key.delete', 'ekm', 'Excluir chaves de criptografia (EKM)', true),
    ('01a1896f-895e-73b9-befc-5b5b20912f6e', 'ekm.key.get',    'ekm', 'Ler chaves de criptografia (EKM)', true),
    ('01a1896f-895e-73b9-befc-5b5c041dc08a', 'ekm.key.list',   'ekm', 'Listar chaves de criptografia (EKM)', true),
    ('01a1896f-895e-73b9-befc-5b5d255cc8f6', 'ekm.key.update', 'ekm', 'Alterar ou rotacionar chaves de criptografia (EKM)', true),
    ('01a1896f-895e-73b9-befc-5b5e367256f5', 'ekm.key.operate', 'ekm', 'Operador: gerenciar qualquer chave de criptografia (EKM)', false),
    -- clm.certificate (roles-clm): certificados digitais (CLM)
    ('01a1896f-895e-73b9-befc-5b5ffae0a805', 'clm.certificate.create', 'clm', 'Emitir certificados digitais (CLM)', true),
    ('01a1896f-895e-73b9-befc-5b600bcb7716', 'clm.certificate.delete', 'clm', 'Revogar certificados digitais (CLM)', true),
    ('01a1896f-895e-73b9-befc-5b61d6ab2425', 'clm.certificate.get',    'clm', 'Ler certificados digitais (CLM)', true),
    ('01a1896f-895e-73b9-befc-5b620195dfc4', 'clm.certificate.list',   'clm', 'Listar certificados digitais (CLM)', true),
    ('01a1896f-895e-73b9-befc-5b63b8fdf540', 'clm.certificate.update', 'clm', 'Renovar ou alterar certificados digitais (CLM)', true),
    ('01a1896f-895e-73b9-befc-5b64b01f3754', 'clm.certificate.operate', 'clm', 'Operador: gerenciar qualquer certificado digital (CLM)', false),
    -- vault.platform (roles-operator): plano de controle do cofre (Vault) (decisão 0104)
    ('01a189a0-1111-7000-8000-000000000001', 'vault.platform.create',  'vault', 'Criar recursos no plano de controle do cofre (Vault)', false),
    ('01a189a0-1111-7000-8000-000000000002', 'vault.platform.delete',  'vault', 'Excluir recursos no plano de controle do cofre (Vault)', false),
    ('01a189a0-1111-7000-8000-000000000003', 'vault.platform.get',     'vault', 'Ler recursos no plano de controle do cofre (Vault)', false),
    ('01a189a0-1111-7000-8000-000000000004', 'vault.platform.list',    'vault', 'Listar recursos no plano de controle do cofre (Vault)', false),
    ('01a189a0-1111-7000-8000-000000000005', 'vault.platform.update',  'vault', 'Alterar recursos no plano de controle do cofre (Vault)', false),
    ('01a189a0-1111-7000-8000-000000000006', 'vault.platform.operate', 'vault', 'Operador: gerenciar o plano de controle do cofre (Vault)', false)
),
inserted AS (
  INSERT INTO ipm.permission (
    resource_id,
    schema_version,
    lifecycle,
    reconciliation,
    desired,
    desired_generation,
    resource_version,
    observed,
    presence,
    observed_at,
    phase,
    conditions,
    observed_generation,
    requested_by,
    correlation_id
  )
  SELECT
    p.resource_id,
    '1.0',
    'present',
    'active',
    jsonb_build_object(
      'lifecycle', 'present',
      'name', p.permission_name,
      'description', p.description,
      'grantable', p.grantable,
      'deletionProtection', true
    ),
    1,
    1,
    jsonb_build_object(
      'name', p.permission_name,
      'description', p.description,
      'group', p.module_group
    ),
    'present',
    now(),
    'Ready',
    jsonb_build_array(
      jsonb_build_object(
        'type', 'Ready',
        'status', 'True',
        'reason', 'Converged',
        'message', 'O estado observado corresponde ao estado desejado.',
        'observedGeneration', 1,
        'lastTransitionAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      ),
      jsonb_build_object(
        'type', 'Progressing',
        'status', 'False',
        'reason', 'Converged',
        'message', 'Nenhuma reconciliação em andamento.',
        'observedGeneration', 1,
        'lastTransitionAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      ),
      jsonb_build_object(
        'type', 'Degraded',
        'status', 'False',
        'reason', 'Healthy',
        'message', 'Sem falhas na geração atual.',
        'observedGeneration', 1,
        'lastTransitionAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      )
    ),
    1,
    'system',
    'seed-vault-modules'
  FROM predefined p
  ON CONFLICT (resource_id) DO NOTHING
  RETURNING resource_id, desired, reconciliation
)
INSERT INTO ipm.permission_outbox (message_id, resource_id, subject, payload)
SELECT
  r.resource_id,
  r.resource_id,
  'desired.ipm.permission.' || r.resource_id,
  jsonb_build_object(
    'messageId', r.resource_id,
    'schemaVersion', '1.0',
    'messageType', 'desired',
    'emitter', 'api',
    'module', 'ipm',
    'resourceType', 'permission',
    'resourceId', r.resource_id,
    'operation', 'changed',
    'desiredGeneration', 1,
    'requestedBy', 'system',
    'correlationId', 'seed-vault-modules',
    'causationId', 'seed-vault-modules',
    'occurredAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'data', jsonb_build_object('reconciliation', r.reconciliation) || r.desired
  )
FROM inserted r
ON CONFLICT (message_id) DO NOTHING;

COMMIT;
