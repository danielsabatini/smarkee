# 0105 — Renomeação do módulo `core` (`core.account`) para `cam` (`cam.account` — Customer Account Manager)

- **Data:** 2026-11-03
- **Status:** Aceita. Evolui e revisa as decisões `0014` (`core.user`), `0027` (organizações `core` e `register`), `0032` (projetos `roles-<módulo>`), `0042` (`core.user` → `core.account`), `0082` (`bsm.account`) e `0083` (`ipm.permission` e `ipm.role`).
- **Origem:** Reavaliação arquitetural (§25.1 do `AGENTS.md`) solicitada pelo responsável do projeto para eliminar a colisão semântica entre a organização/namespace de sistema `core` (Zitadel e OpenBao) e o módulo de produto responsável pela conta do cliente, além de desambiguar `cam.account` (*Customer Account*, `--customer-account`) de `bsm.account` (*Billing Account*, `--billing-account`).

## Contexto

Historicamente, a plataforma utilizava a palavra `core` com dois significados distintos:

1. **Infraestrutura e Identidade de Sistema (`core`):** a organização técnica interna no Zitadel (`PLATFORM_ORGANIZATION_ID = "core"`, decisões `0027` e `0084`), dona dos projetos de catálogo de permissões (`roles-<módulo>`) e das *service accounts* dos controllers (`*-controller`), bem como o namespace `core/` no OpenBao (`smarkee-core-svm`, decisão `0102`).
2. **Módulo de Produto (`core/account`):** a feature responsável pelo auto-cadastro (onboarding) e ciclo de vida da conta raiz do cliente na plataforma (`features/core/account`, `/v1/core/accounts`).

Além da sobrecarga do termo `core`, todos os demais módulos de produto da Smarkee adotam a convenção de siglas de 3 letras terminadas em `M` (*Manager*): `ipm` (*Identity Provider Manager*), `sum` (*Service Usage Manager*), `bsm` (*Billing Service Manager*), `svm` (*Secret Vault Manager*), `ekm` (*Encryption Key Manager*) e `clm` (*Certificate Lifecycle Manager*). A coexistência de `core/account` e `bsm/account` também gerava ambiguidade quando recursos precisavam referenciar a conta raiz do titular versus a conta de faturamento.

## Decisão

1. **O módulo da conta do cliente passa a se chamar `cam` (*Customer Account Manager*):**
   - Feature e pacote: `features/cam/account` (`cam_account`), containers `cam-account-{api,publisher,controller,telemeter}` e variáveis `CAM_ACCOUNT_*`.
   - Contratos: `schemas/cam/account/` e índice `schemas/cam.account.index.json`.
   - Rotas HTTP no Gateway: `/v1/cam/accounts`, `/v1/cam/accounts/{resourceId}` e `/v1/cam/accounts/registration-status/{ticket}`.
   - Banco de dados (`ssot`): schema SQL `cam`, tabelas `cam.account`, `cam.account_outbox`, `cam.account_idempotency`, `cam.account_operation` e `cam.account_registration_ticket`, e papéis `cam_account_api`, `cam_account_controller`, `cam_account_publisher` e `cam_maintenance`.
   - Mensageria (NATS JetStream): subjects `desired.cam.account.<id>` e `updated.cam.account.<id>`.
   - Identidade e Permissões: projeto `roles-cam` (dentro da organização de sistema `core` no Zitadel), permissões atômicas `cam.account.get`, `cam.account.delete` e `cam.account.operate`, e roles predefinidas `cam.accountViewer` e `cam.accountAdmin`.
   - Kubernetes e OpenBao: namespace de aplicação `cam`, `Application` ArgoCD `feature-cam-account` e segredo `/svm/data/features/cam/account` (dentro do namespace `core/` do OpenBao).
2. **Simetria na CLI `sk`:**
   - Os comandos da Customer Account seguem a estrutura simétrica `sk <módulo> <tipo> <ação>`: `sk cam account create|status|get|protect|unprotect|delete`.
   - A chave de configuração do projeto de permissões na CLI passa a ser `cam.projectId` (`SK_CAM_PROJECT_ID`).
3. **`core` permanece estritamente como identificador da organização/namespace de sistema:**
   - No Zitadel: organização `core` (`PLATFORM_ORGANIZATION_ID = "core"`, dona dos projetos `roles-*`, das Roles predefinidas em `ipm.role` e das *service accounts* de infraestrutura).
   - No OpenBao: namespace `core` e `ClusterSecretStore` `smarkee-core-svm`.
4. **Distinção terminológica explícita entre contas:**
   - **`cam.account` (*Customer Account*):** referenciada em contratos e na CLI como `customerAccountId` / `--customer-account`.
   - **`bsm.account` (*Billing Account*):** referenciada em contratos e na CLI como `billingAccountId` / `--billing-account`.
