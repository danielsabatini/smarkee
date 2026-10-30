-- Migração 0005 de ipm.role: papéis pré-definidos dos módulos de cofre (svm), criptografia (ekm) e PKI (clm) (decisões 0102 e 0103).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente: pode ser reaplicada.

BEGIN;

WITH predefined(resource_id, role_name, description, permissions) AS (
  VALUES
    (
      '01a1896f-8966-77e1-b658-a42c65ba7195',
      'svm.secretViewer',
      'Leitura de segredos no cofre em svm.secret.',
      '["svm.secret.get", "svm.secret.list"]'::jsonb
    ),
    (
      '01a1896f-8966-77e1-b658-a42d1f64a622',
      'svm.secretAdmin',
      'Administração de segredos no cofre em svm.secret.',
      '["svm.secret.create", "svm.secret.delete", "svm.secret.get", "svm.secret.list", "svm.secret.update"]'::jsonb
    ),
    (
      '01a1896f-8966-77e1-b658-a42e3ad5ef99',
      'ekm.keyViewer',
      'Leitura de chaves de criptografia em ekm.key.',
      '["ekm.key.get", "ekm.key.list"]'::jsonb
    ),
    (
      '01a1896f-8966-77e1-b658-a42fad1a6a17',
      'ekm.keyAdmin',
      'Administração de chaves de criptografia em ekm.key.',
      '["ekm.key.create", "ekm.key.delete", "ekm.key.get", "ekm.key.list", "ekm.key.update"]'::jsonb
    ),
    (
      '01a1896f-8966-77e1-b658-a430f2992357',
      'clm.certificateViewer',
      'Leitura de certificados digitais em clm.certificate.',
      '["clm.certificate.get", "clm.certificate.list"]'::jsonb
    ),
    (
      '01a1896f-8966-77e1-b658-a4313d9623e8',
      'clm.certificateAdmin',
      'Administração de certificados digitais em clm.certificate.',
      '["clm.certificate.create", "clm.certificate.delete", "clm.certificate.get", "clm.certificate.list", "clm.certificate.update"]'::jsonb
    ),
    -- vault.platform (roles-operator): plano de controle do cofre (Vault) (decisão 0104)
    (
      '01a189a0-2222-7000-8000-000000000001',
      'vault.platformViewer',
      'Leitura e auditoria do plano de controle e dos segredos do cofre (Vault).',
      '["vault.platform.get", "vault.platform.list", "svm.secret.get", "svm.secret.list", "ekm.key.get", "ekm.key.list", "clm.certificate.get", "clm.certificate.list"]'::jsonb
    ),
    (
      '01a189a0-2222-7000-8000-000000000002',
      'vault.platformAdmin',
      'Administração completa do plano de controle e dos recursos do cofre (Vault).',
      '["vault.platform.create", "vault.platform.delete", "vault.platform.get", "vault.platform.list", "vault.platform.update", "vault.platform.operate", "svm.secret.create", "svm.secret.delete", "svm.secret.get", "svm.secret.list", "svm.secret.update", "svm.secret.operate", "ekm.key.create", "ekm.key.delete", "ekm.key.get", "ekm.key.list", "ekm.key.update", "ekm.key.operate", "clm.certificate.create", "clm.certificate.delete", "clm.certificate.get", "clm.certificate.list", "clm.certificate.update", "clm.certificate.operate"]'::jsonb
    )
),
inserted AS (
  INSERT INTO ipm.role (
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
      'name', p.role_name,
      'roleType', 'predefined',
      'description', p.description,
      'permissions', p.permissions,
      'deletionProtection', true
    ),
    1,
    1,
    jsonb_build_object(
      'name', p.role_name,
      'description', p.description,
      'permissions', p.permissions,
      'deletionProtection', true
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
INSERT INTO ipm.role_outbox (message_id, resource_id, subject, payload)
SELECT
  r.resource_id,
  r.resource_id,
  'desired.ipm.role.' || r.resource_id,
  jsonb_build_object(
    'messageId', r.resource_id,
    'schemaVersion', '1.0',
    'messageType', 'desired',
    'emitter', 'api',
    'module', 'ipm',
    'resourceType', 'role',
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
