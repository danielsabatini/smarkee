# 0103 — Autenticação OIDC/JWT e RBAC unificado Zitadel e Vault (OpenBao)

- **Data:** 2026-10-29
- **Status:** Aceita. Estende as decisões `0006` (Organization como unidade de isolamento), `0034` (projeto `clients` no Zitadel), `0084` (organização `operator` e `roles-operator`) e `0102` (Kubernetes, kind e Vault). Complementada pela decisão `0104` (permissões atômicas CRUD no cofre, substituição de `*.admin` por `*.operate` e roles `vault.platformAdmin` / `vault.platformViewer`).

## Contexto

A plataforma adota o Zitadel como Provedor de Identidade (IdP) e fonte única da verdade de autorização baseada em papéis (RBAC). Com a introdução do OpenBao (`vault`) na decisão `0102`, estabeleceu-se a correspondência 1:1 entre as organizações do Zitadel e os namespaces do Vault (`core/`, `operator/` e `<organizationId>/` para cada tenant).

No estágio inicial do cluster Kubernetes de desenvolvimento, o acesso à interface Web do OpenBao (`http://127.0.0.1:8200/ui/`) e às suas APIs era realizado utilizando o `root_token` gerado no bootstrap. Essa prática contraria os princípios de segurança do `AGENTS.md` (§4) para operação contínua, pois o `root_token` não possui rastreabilidade nominal por operador, contorna o ciclo de vida do IdP e não deve ser exposto na rotina diária.

Adicionalmente, as futuras features de produto da plataforma que expõem capacidades criptográficas e de custódia de segredos para clientes finais (`svm` — *Secret Vault Manager*, `ekm` — *Encryption Key Manager*, e `clm` — *Certificate Lifecycle Manager*) exigem uma taxonomia padronizada de permissões granulares (`<módulo>.<tipo>.<ação>`) perfeitamente mapeada no IdP e refletida nas políticas internas do cofre.

## Decisão

1. **Três Domínios de Isolamento Simétricos (Zitadel ↔ OpenBao):**
   - **`core` (Plataforma / Máquinas):**
     - No Zitadel: organização `core` abriga as *Service Accounts* dos componentes da plataforma e os projetos de permissões de ação por módulo.
     - No OpenBao: namespace `core/` abriga os segredos, chaves e CAs internas da plataforma nos mounts `/svm`, `/ekm` e `/clm`.
     - Autenticação: as *Service Accounts* autenticam via `auth/jwt` (JWT Profile assinado com suas chaves privadas RSA `key.json`) e recebem políticas HCL do OpenBao homônimas às suas roles do Zitadel.
     - Exceção de Boot (Fase 1): o `External Secrets Operator` (ESO) e o `cert-manager` utilizam `auth/kubernetes` estritamente durante o bootstrap para projetar segredos estáticos e certificados nos Pods, sem participação de credenciais humanas.
   - **`operator` (Operadores da Plataforma / Humanos):**
     - No Zitadel: organização `operator` abriga os operadores humanos (ex.: `admin@operator.smarkee.internal`), o projeto `roles-operator` (permissões `*.admin`) e um novo projeto `clients` (sem roles, conforme decisão `0034`).
     - No OpenBao: namespace `operator/` e permissão administrativa sobre `core/`.
     - Autenticação: operadores humanos autenticam-se na Web UI (`:8200/ui/`) e na CLI (`bao login -method=oidc`) via **OIDC federado com o Zitadel**. O `auth/oidc` restringe o acesso por `bound_claims` à organização `operator` (`urn:zitadel:iam:user:resourceowner:id == <OPERATOR_ORG_ID>`) e à presença de permissões `*.admin`.
   - **`<cliente>` (Organizações de Clientes / Tenants):**
     - No Zitadel: organização `<organizationId>` recebe *Project Grants* dos módulos que contratar via SUM (`roles-svm`, `roles-ekm`, `roles-clm`).
     - No OpenBao: namespace `<organizationId>/` com mounts isolados `/svm`, `/ekm` e `/clm`.
     - Acesso: clientes **nunca acessam a porta 8200 do OpenBao diretamente**. O acesso é 100% mediado pelas APIs síncronas da Smarkee (`/v1/svm`, `/v1/ekm`, `/v1/clm`), CLI `sk` e Smarkee Console. O controlador da feature atua no namespace `<organizationId>/` em nome do cliente.

2. **Novos Módulos no Catálogo de Permissões (`ipm/permission`) e Roles (`ipm/role`):**
   - Criação de três novos projetos de roles na organização `core`:
     - **`roles-svm`:** permissões `svm.secret.{create,delete,get,list,update}` (`grantable = true`) e `svm.secret.admin` (`grantable = false`, em `roles-operator`).
     - **`roles-ekm`:** permissões `ekm.key.{create,delete,get,list,update}` (`grantable = true`) e `ekm.key.admin` (`grantable = false`, em `roles-operator`).
     - **`roles-clm`:** permissões `clm.certificate.{create,delete,get,list,update}` (`grantable = true`) e `clm.certificate.admin` (`grantable = false`, em `roles-operator`).
   - Criação de Roles compostas pré-definidas em `ipm/role`:
     - `svm.secretViewer`, `svm.secretAdmin`
     - `ekm.keyViewer`, `ekm.keyAdmin`
     - `clm.certificateViewer`, `clm.certificateAdmin`

3. **Aplicação OIDC `vault` na Organização `operator`:**
   - Registrada no projeto `clients` da organização `operator` (`projectRoleAssertion = true`, `authorizationRequired = false`).
   - Tipo de aplicação: Web com PKCE (`OIDC_APP_TYPE_WEB`).
   - Redirect URIs permitidos:
     - `http://127.0.0.1:8200/ui/vault/auth/oidc/oidc/callback`
     - `http://localhost:8200/ui/vault/auth/oidc/oidc/callback`
     - `http://127.0.0.1:8250/oidc/callback` (CLI `bao login`)

4. **Políticas HCL Homônimas no OpenBao:**
   - Para cada permissão granular do Zitadel (`svm.secret.get`, `ekm.key.create`, etc.), o OpenBao mantém uma *Policy* HCL correspondente que restringe caminhos e capacidades aos limites daquela ação.
   - O `root_token` é restrito a funções de *bootstrap* do cluster e recuperação de desastre (*break-glass*), arquivado com segurança fora da rotina operacional.

## Consequências

- **Segurança:** O Zitadel passa a ser a autoridade central indiscutível de RBAC. A revogação de papéis no Zitadel reflete imediatamente no OpenBao. Nenhuma credencial estática de superusuário é utilizada no dia a dia.
- **Simplicidade:** O mapeamento utiliza claims e recursos nativos dos dois softwares, sem necessidade de sincronizadores intermediários ou scripts customizados.
- **Evolução Aditiva:** A infraestrutura de permissões, projetos e políticas HCL provisionada atende tanto à operação interna do cluster quanto às futuras features comerciais `svm`, `ekm` e `clm`.
