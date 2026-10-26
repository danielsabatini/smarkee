# 0082 — Billing & FinOps (FOCUS 1.4) e o módulo `bsm/account`

- **Data:** 2026-10-22
- **Status:** Aceita e implementada em dev (fase P0 de `docs/billing/BILLING.md`).
- **Origem:** definição da arquitetura de Billing e FinOps da plataforma Smarkee e criação do módulo `bsm` (*Billing Service Manager*) com o seu primeiro recurso, `bsm.account` (`/v1/bsm/accounts`).

## Decisão

1. **Conformidade nativa com o padrão FOCUS 1.4 (`docs/billing/BILLING.md`).**
   - Os artefatos financeiros e de telemetria de uso da plataforma seguem a versão estável **FOCUS 1.4** da FinOps Foundation (`Cost and Usage`, `Billing Period`, `Invoice Detail` e `Contract Commitment`).
   - Os identificadores e colunas normativas preservam a semântica oficial: `BillingAccountId` (`bsm.account`), `SubAccountId` (`ipm.organization`), `ServiceProviderName`, `HostProviderName`, `InvoiceIssuerName`, `SkuId`, `SkuPriceId`, `SkuMeter`, `ChargeClass` e `ContractedCost`.

2. **Separação estrita entre identidade de acesso e identidade financeira.**
   - `core.account` representa exclusivamente a pessoa autenticada na plataforma; `bsm.account` representa o contrato pagador (`BillingAccountId`).
   - Uma pessoa (`core.account`) pode criar e possuir múltiplas Billing Accounts (`ownerAccountId` imutável no `desired`, omitido na visão pública), por exemplo para separar moedas (`BRL`, `USD`, `EUR`) ou centros de custo.
   - `ipm.organization` (`SubAccountId`) recebe o campo aditivo e opcional `billingAccountId` no `desired` e nos contratos de criação e atualização (`POST`/`PATCH /v1/ipm/organizations`), referenciando a `bsm.account` que paga pelos recursos daquela Organization.

3. **Separação entre o plano mutável de recursos e o plano imutável de fatos financeiros.**
   - Entidades cadastrais e de configuração (`bsm.account`, `bsm.export`, `ipm.organization`) usam o **Resource Control Loop** (`docs/loop/RESOURCE-CONTROL-LOOP.md`) sobre o SSOT em PostgreSQL (`docs/data/SSOT.md`).
   - Fatos financeiros (`Metering`, `Pricing` e `Invoicing`) usam um pipeline assíncrono **append-only** via NATS JetStream, sem reconciliação nem mutação retroativa: períodos fechados são corrigidos exclusivamente por lançamentos compensatórios com `ChargeClass = "Correction"`.
   - É **vedado** usar o pipeline de observabilidade OpenTelemetry (`docs/telemetry/OBSERVABILITY-ARCHITECTURE.md`) para transportar eventos de `Metering`, pois coletores de telemetria admitem descarte e amostragem sob pressão.

4. **Armazenamento em disco local na fase P0 (`bsm.account`).**
   - Para entregar valor imediato sem acoplamento prematuro a gateways de pagamento externos ou motores analíticos pesados, o provedor do Executor e do Observer de `bsm/account` em P0 persiste o estado observado em arquivos JSON atômicos (`write` + `fsync` + `os.replace`) num volume compartilhado (`bsm-account-state`).
   - A migração futura para um gateway externo na fase P2 altera apenas `provider/` e `drivers/` de `bsm/account`, mantendo intactos os contratos JSON Schema v1.0, o SSOT, o Receiver, o Manager, o Publisher e o Reconciler (§2.6 do `AGENTS.md`).

5. **BSM como capacidade de nível de conta (`core.account`), conta inicial `"Free Tier"` e pré-requisito para serviços (`sum/service` e `ipm/organization`).**
   - Diferente de `ipm` (que é um serviço habilitável no SUM), o módulo `bsm` é uma capacidade básica do nível de `core.account` (`roles-bsm`: `bsm.account.create|get|list|update|delete` concedidas automaticamente por `DEFAULT_PLATFORM_ROLES` no cadastro da conta, com `core-account-executor` como `PROJECT_GRANT_OWNER` de `roles-bsm`, e `bsm.account.admin` fora do Project Grant). Não existem roles `sum.bsm.*` em `roles-sum`.
   - Quando o `core.account` converge (`manager.updated.core.account.<accountId>.changed` com `phase == "Ready"` e `lifecycle == "present"`), o consumer durável `bsm-account-manager-account-updated` do Manager de `bsm.account` lê o `email` na última mensagem `manager.desired.core.account.<accountId>.changed` (Stream `DESIRED`) e provisiona de forma idempotente uma Billing Account inicial (`displayName = "Free Tier"`, `billingCurrency = "BRL"`, `billingContacts = [<email>]`, `deletionProtection = true`).
   - O Receiver do `sum/service` exige que o solicitante possua pelo menos uma `bsm.account` ativa (`phase == "Ready"` e `desired.lifecycle == "present"`) antes de habilitar qualquer serviço (`POST /v1/sum/services`), recusando com `409 BillingAccountRequired` caso contrário.
   - O Receiver de `ipm/organization` valida o `billingAccountId` informado contra `GET /v1/bsm/accounts/{billingAccountId}` (`409 BillingAccountNotReady` se inexistente ou não `Ready`), e o Receiver de `bsm/account` consulta `GET /v1/ipm/organizations` antes de excluir uma Billing Account, recusando com `409 ResourcesAttached` enquanto houver Organizations vinculadas a ela.
   - O Receiver do `core/account` consulta `GET /v1/bsm/accounts` antes de excluir a conta, recusando com `409 ResourcesAttached` enquanto o usuário possuir Billing Accounts ativas.

## Justificativa

- **Segurança:** isolamento de credenciais por papel no PostgreSQL (`bsm_account_receiver_login`, `bsm_account_manager_login`, `bsm_account_publisher_login`), audiência própria no Zitadel (`roles-bsm`) e proteção contra exclusão (`deletionProtection = true` por padrão, decisão 0043).
- **Simplicidade:** um único modelo de loop para `bsm.account` (gerado e verificado por `templates/feature/sync.py`) e armazenamento local em disco na fase P0, evitando dependências externas antes da validação do domínio.
- **Robustez:** `billingCurrency` imutável após a criação (`ImmutableField`), `billingContacts` normalizados e sem duplicatas, e verificação explícita de dependentes no SUM e na Account antes de desabilitar o serviço ou excluir a conta.
- **Resiliência:** escrita atômica em disco com `os.replace`, idempotência de ponta a ponta por `Idempotency-Key` e `Nats-Msg-Id`, e desacoplamento assíncrono via NATS JetStream.

## Compatibilidade

- `schemas/bsm/account/` inaugura o contrato `1.0` do módulo `bsm`.
- Em `schemas/ipm/organization/`, o campo `billingAccountId` é opcional nos contratos `1.0` (`api-create-request`, `api-update-request`, `requested-create`, `requested-update`, `desired` e `resource`), preservando total compatibilidade com clientes e Organizations existentes.

## Verificação (dev, 2026-10-22)

- Validação de todos os JSON Schemas e exemplos em `schemas/` (`590 passed`).
- Verificação de sincronia do template (`templates/feature/sync.py --check`), lint (`ruff`), formatação, tipagem estrita (`pyright`) e testes unitários, de contrato, de integração e e2e em `features/bsm/account`, `features/sum/service`, `features/core/account`, `features/ipm/organization` e `clients/cli` (`sk bsm account` e `sk ipm organization --billing-account-id`).
- Suíte de conformidade da identidade (`infrastructure/dev/identity/conformance`, `20 passed`) e Quality Gate do SonarQube aprovado para `bsm/account`.
