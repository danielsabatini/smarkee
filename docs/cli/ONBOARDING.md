# Guia Completo de Onboarding, Operação e Desmonte com a CLI `sk`

Este documento apresenta o roteiro completo de ponta a ponta para validar todas as capacidades da plataforma Smarkee através da CLI `sk`. O roteiro está organizado **por feature** do ecossistema, cobrindo o ciclo de vida completo de cada recurso desde o provisionamento até o desmonte ordenado.

> **Padrão de Execução:** Todos os comandos usam o formato a partir da raiz do repositório (`uv run --project clients/cli sk <comando>`). Se estiver dentro do diretório `clients/cli`, utilize `uv run sk <comando>`.
>
> **Convergência Síncrona por Padrão (`--wait` vs `--no-wait`):** Todos os comandos de mutação da CLI (criação, atualização, alteração de proteção, ativação/desativação e exclusão) operam por padrão com `--wait` ativo, aguardando a convergência do recurso (geração observada e fase `Ready` ou exclusão concluída). Para despachar a mutação assincronamente e liberar o terminal de imediato, utilize a opção `--no-wait`.

---

## Índice por Feature

1. [Preparação do Ambiente (`clients/cli`)](#1-preparação-do-ambiente-clientscli)
2. [Feature `cam.account` — Onboarding, Identidade e Conta do Cliente (Customer Account Manager)](#2-feature-camaccount--onboarding-identidade-e-conta-do-cliente-customer-account-manager)
3. [Feature `sum.service` (Etapa 1) — Habilitação do Serviço `bsm`](#3-feature-sumservice-etapa-1--habilitação-do-serviço-bsm)
4. [Feature `bsm.account` — Unidade de Cobrança (Billing Service Manager)](#4-feature-bsmaccount--unidade-de-cobrança-billing-service-manager)
5. [Feature `sum.service` (Etapa 2) — Habilitação do Serviço `ipm`](#5-feature-sumservice-etapa-2--habilitação-do-serviço-ipm)
6. [Feature `ipm.organization` — Gestão de Organizações](#6-feature-ipmorganization--gestão-de-organizações)
7. [Features `ipm.permission` e `ipm.role` — Catálogo IAM de Permissões e Roles](#7-features-ipmpermission-e-ipmrole--catálogo-iam-de-permissões-e-roles)
8. [Feature `ipm.group` — Grupos da Organização](#8-feature-ipmgroup--grupos-da-organização)
9. [Feature `ipm.user` — Membros e Usuários da Organização](#9-feature-ipmuser--membros-e-usuários-da-organização)
10. [Feature `ipm.serviceaccount` — Identidades de Máquina (M2M)](#10-feature-ipmserviceaccount--identidades-de-máquina-m2m)
11. [Desmonte Ordenado e Exclusão Total (Hierarquia Reversa)](#11-desmonte-ordenado-e-exclusão-total-hierarquia-reversa)

---

## 1. Preparação do Ambiente (`clients/cli`)

Certifique-se de que a stack local ou cluster Kubernetes esteja ativo e os domínios mapeados em `/etc/hosts`:

```text
127.0.0.1 api-dev.smarkee.com.br ipm-dev.smarkee.com.br mail-dev.smarkee.com.br
```

Carregue as variáveis de ambiente necessárias para a CLI apontar para o gateway de desenvolvimento:

```bash
source clients/cli/.env
```

---

## 2. Feature `cam.account` — Onboarding, Identidade e Conta do Cliente (Customer Account Manager)

O módulo `cam.account` gerencia o ciclo de vida da conta de cliente (**Customer Account**) e do usuário raiz no provedor de identidade (Zitadel).

### 2.1 Auto-cadastro Síncrono (`--wait`, padrão)
Solicite o cadastro da conta. Por padrão, a CLI adota `--wait`, aguardando a criação assíncrona no provedor e o envio do e-mail de ativação:

```bash
uv run --project clients/cli sk cam account create \
  --name "Ana" \
  --surname "Souza" \
  --email "ana.souza@empresa.com"
```

**Saída esperada:**
```text
waiting: request accepted (0 s of 60 s)
waiting: provisioning (pending) (0 s of 60 s)
waiting: provisioning (ready) (1 s of 60 s)
╭─ ✓ Account registration accepted ────────────────────────────────────────────────╮
│ name             Ana Souza                                                       │
│ email            ana.souza@empresa.com                                           │
│ resourceId       01a18cc9-2bc2-7483-903c-797014939e89                            │
│ phase            Ready                                                           │
│ emailDispatched  yes                                                             │
╰──────────────────────────────────────────────────────────────────────────────────╯
Provisioning completed and activation e-mail sent to ana.souza@empresa.com.
```

### 2.2 Alternativa Assíncrona com Ticket (`--no-wait`)
Caso prefira retorno imediato sem reter o terminal, utilize `--no-wait`. A plataforma emite um **Ticket de Rastreamento** temporário (UUIDv7, TTL de 30 minutos):

```bash
uv run --project clients/cli sk cam account create \
  --name "Ana" \
  --surname "Souza" \
  --email "ana.souza@empresa.com" \
  --no-wait
```

#### Consultar o Status por Ticket:
```bash
uv run --project clients/cli sk cam account status --ticket <TICKET_UUID>
```

#### Solicitar Reenvio de E-mail de Ativação (com Rate Limiting de 60s):
```bash
uv run --project clients/cli sk cam account status --ticket <TICKET_UUID> --resend
```

### 2.3 Ativação no Mailpit e Cadastro de Senha
1. Abra a caixa de entrada no **Mailpit**: [http://localhost:8025](http://localhost:8025)
2. Abra o e-mail de verificação enviado para `ana.souza@empresa.com`.
3. Clique em **Verificar e-mail**.
4. Na tela do Zitadel (`http://ipm-dev.smarkee.com.br:8080`), cadastre uma senha inicial (ex: `SenhaSegura@123`).

### 2.4 Login OIDC e Inspeção da Conta do Cliente
Autentique-se via navegador e confira os dados da sessão:

```bash
# Efetuar o login OIDC (abre o navegador)
uv run --project clients/cli sk auth login

# Verificar a sessão ativa
uv run --project clients/cli sk auth whoami

# Inspecionar os detalhes da sua Customer Account
uv run --project clients/cli sk cam account get
```
*(Anote o `resourceId` da sua Customer Account ou fixe-o com `uv run --project clients/cli sk config set cam.accountId <CUSTOMER_ACCOUNT_ID>`)*.

---

## 3. Feature `sum.service` (Etapa 1) — Habilitação do Serviço `bsm`

No auto-cadastro (`cam.account`), a conta recebe apenas as permissões `cam.account.{delete,get}`, `sum.bsm.{disable,enable,get}` e `sum.ipm.{disable,enable,get}` (menor privilégio, decisão `0105`). Para gerenciar contas de faturamento (`bsm.account`), habilite primeiro o serviço **`bsm`** no catálogo `sum.service`.

### 3.1 Descobrir Serviços no Catálogo (`--available`)

Consulte quais serviços estão disponíveis na plataforma:

```bash
uv run --project clients/cli sk sum service list --available
```

**Saída esperada:**
```text
╭─ Available Services ─────────────────────────────────────────────────────────────╮
│ name  title                      state      description                          │
│ bsm   Billing Service Manager    available  Manage billing accounts, contacts,   │
│                                             currencies and spending controls.    │
│ ipm   Identity Provider Manager  available  Manage organizations, identities,    │
│                                             groups, permissions and service      │
│                                             accounts.                            │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

### 3.2 Habilitar o Serviço `bsm` (`sk sum service enable --service bsm`)

Habilite o serviço `bsm` (que não exige uma Billing Account prévia) para receber as permissões `bsm.account.{create,delete,get,list,update}` e `bsm.payment.{create,delete,get,list,update}` e renovar automaticamente o token da sessão OIDC:

```bash
uv run --project clients/cli sk sum service enable --service bsm
```

---

## 4. Feature `bsm.account` — Unidade de Cobrança (Billing Service Manager)

O módulo `bsm.account` gerencia as unidades de faturamento e limites de cobrança associadas explicitamente a uma Customer Account (`customerAccountId`).

Cada `customerAccountId` suporta:
- **`--type free`**: até **1** conta ativa sem exigência de método de pagamento.
- **`--type paid`**: até **5** contas ativas, exigindo `--payment-id` de um Método de Pagamento (`bsm.payment`) do mesmo `customerAccountId` (seção 4.2).

### 4.1 Criar uma Billing Account `free`

```bash
# Criar uma Billing Account gratuita associada à Customer Account
uv run --project clients/cli sk bsm account create \
  --type free \
  --customer-account <CUSTOMER_ACCOUNT_ID> \
  --display-name "Free Tier" \
  --currency BRL \
  --billing-contacts ana.souza@empresa.com
```
*(Se `cam.accountId` já estiver salvo via `sk config set cam.accountId <CUSTOMER_ACCOUNT_ID>`, o parâmetro `--customer-account` pode ser omitido. O parâmetro `--billing-contacts` aceita repetição ou e-mails separados por vírgula).*

**Saída esperada:**
```text
waiting: request accepted (0 s of 60 s)
waiting: provisioning (ready) (0 s of 60 s)
╭─ ✓ Billing Account created ──────────────────────────────────────────────────────╮
│ displayName        Free Tier                                                     │
│ type               free                                                          │
│ customerAccountId  01a18cc9-2bc2-7483-903c-797014939e89                          │
│ currency           BRL                                                           │
│ resourceId         01a18cc9-7970-7483-903c-2bc214939e89                          │
│ phase              Ready                                                         │
│ protected          yes                                                           │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

### 4.2 (Opcional) Criar uma Billing Account `paid` com Método de Pagamento (`bsm.payment`)

Uma conta `--type paid` exige um Método de Pagamento (`bsm.payment`, decisão `0106`) registrado e validado no gateway externo (Mercado Pago). A CLI recebe apenas um *nonce* descartável emitido pelo SDK do gateway (`--card-nonce`): número do cartão e CVV nunca são informados nem persistidos. Em dev, o modo de simulação aceita nonces como `sim_visa_4242`.

```bash
# Registrar o método de pagamento e aguardar a validação no gateway
uv run --project clients/cli sk bsm payment create \
  --customer-account <CUSTOMER_ACCOUNT_ID> \
  --display-name "Visa corporativo" \
  --card-nonce sim_visa_4242
```

Copie o `resourceId` do método de pagamento e crie a conta paga:

```bash
uv run --project clients/cli sk bsm account create \
  --type paid \
  --customer-account <CUSTOMER_ACCOUNT_ID> \
  --payment-id <PAYMENT_ID> \
  --display-name "Produção" \
  --currency BRL \
  --billing-contacts "financeiro@empresa.com,ana.souza@empresa.com"
```

Enquanto uma Billing Account ativa referenciar o método de pagamento, a exclusão dele responde `409 ResourcesAttached`. Para trocar o método de uma conta existente, use `sk bsm account update --payment-id <NOVO_PAYMENT_ID>`.

### 4.3 Listar, Inspecionar e Fixar na Configuração Local

```bash
# Listar as contas de cobrança disponíveis
uv run --project clients/cli sk bsm account list
```
*(Copie o `resourceId` da conta, ex: `01a18...`)*.

```bash
# Visualizar detalhes da conta de cobrança
uv run --project clients/cli sk bsm account get --resource-id <BILLING_ACCOUNT_ID>

# Fixar a conta de cobrança na configuração local da CLI
uv run --project clients/cli sk config set bsm.accountId <BILLING_ACCOUNT_ID>

# Conferir o valor salvo
uv run --project clients/cli sk config get bsm.accountId
```

---

## 5. Feature `sum.service` (Etapa 2) — Habilitação do Serviço `ipm`

Com uma Billing Account ativa em `bsm.account`, habilite o serviço **`ipm`** (Identity Provider Manager) para gerenciar organizações e identidades:

```bash
# Habilitar o serviço IPM (aguarda Ready e renova a sessão por padrão)
uv run --project clients/cli sk sum service enable --service ipm
```

*(Para retorno assíncrono imediato sem aguardar, use `sk sum service enable --service ipm --no-wait`).*

**Saída esperada:**
```text
waiting: request accepted (0 s of 60 s)
waiting: provisioning (ready) (1 s of 60 s)
╭─ ✓ Service enabled ──────────────────────────────────────────────────────────────╮
│ resourceId           01a18d20-4e56-7483-903c-2bc214939e89                        │
│ service              ipm                                                         │
│ state                enabled                                                     │
│ phase                Ready                                                       │
│ observedPermissions  ipm.organization.create, ipm.organization.list, ...        │
│ session              renewed                                                     │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

### 5.1 Inspecionar Serviços Ativados

```bash
# Listar os serviços habilitados para a sua conta (bsm e ipm)
uv run --project clients/cli sk sum service list

# Conferir detalhes específicos dos serviços habilitados
uv run --project clients/cli sk sum service get --service bsm
uv run --project clients/cli sk sum service get --service ipm
```

---

## 6. Feature `ipm.organization` — Gestão de Organizações

O módulo `ipm.organization` gerencia organizações como tenants no provedor de identidade. Toda organização exige uma Billing Account ativa associada.

```bash
# Criar uma nova organização
uv run --project clients/cli sk ipm organization create \
  --name "acme" \
  --display-name "ACME Corporation" \
  --billing-account-id <BILLING_ACCOUNT_ID> \
  --wait
```
*(Copie o `resourceId` da organização criada)*.

```bash
# Listar as organizações sob seu controle
uv run --project clients/cli sk ipm organization list

# Fixar a organização ativa na configuração local da CLI
uv run --project clients/cli sk config set ipm.organizationId <ORGANIZATION_ID>

# Inspecionar detalhes da organização
uv run --project clients/cli sk ipm organization get
```

---

## 7. Features `ipm.permission` e `ipm.role` — Catálogo IAM de Permissões e Roles

As features `ipm.permission` e `ipm.role` controlam o catálogo de permissões atômicas e roles compostas pré-definidas no padrão Google Cloud IAM.

```bash
# Listar as permissões atômicas registradas no catálogo da plataforma
uv run --project clients/cli sk ipm permission list

# Listar as roles compostas disponíveis (ex: ipm.organizationAdmin, ipm.organizationViewer)
uv run --project clients/cli sk ipm role list
```

---

## 8. Feature `ipm.group` — Grupos da Organização

O módulo `ipm.group` gerencia agrupamentos lógicos de identidades na organização.

```bash
# Criar um grupo na organização ativa
uv run --project clients/cli sk ipm group create \
  --name "engenharia" \
  --display-name "Time de Engenharia"

# Listar os grupos existentes
uv run --project clients/cli sk ipm group list
```
*(Copie o `resourceId` do grupo criado)*.

---

## 9. Feature `ipm.user` — Membros e Usuários da Organização

O módulo `ipm.user` gerencia membros convidados e suas roles atribuídas dentro da organização.

```bash
# Convidar um usuário atribuindo uma role composta do catálogo IAM
uv run --project clients/cli sk ipm user create \
  --email "carlos.silva@empresa.com" \
  --given-name "Carlos" \
  --family-name "Silva" \
  --roles "ipm.organizationViewer" \
  --wait
```
*(Copie o `resourceId` do usuário criado)*.

```bash
# Listar os usuários da organização
uv run --project clients/cli sk ipm user list

# Visualizar detalhes e permissões efetivas calculadas do usuário
uv run --project clients/cli sk ipm user get --resource-id <USER_ID>
```

---

## 10. Feature `ipm.serviceaccount` — Identidades de Máquina (M2M)

O módulo `ipm.serviceaccount` gerencia identidades não humanas para pipelines e automações, gerando chaves RSA localmente em arquivos seguros (`0600`).

```bash
# Criar uma service account na organização (par RSA gerado localmente)
uv run --project clients/cli sk ipm serviceaccount create \
  --name "ci-deployer" \
  --display-name "Pipeline CI/CD" \
  --roles "ipm.organizationViewer" \
  --wait
```
*(Copie o `resourceId` da Service Account criada)*.

```bash
# Listar service accounts da organização
uv run --project clients/cli sk ipm serviceaccount list

# Inspecionar chaves públicas registradas na service account
uv run --project clients/cli sk ipm serviceaccount key list --resource-id <SA_ID>
```

---

## 11. Desmonte Ordenado e Exclusão Total (Hierarquia Reversa)

A plataforma impõe proteção contra exclusão acidental e exige a **remoção hierárquica inversa**: recursos filhos devem ser removidos antes dos contêineres e serviços atrelados.

```text
Service Accounts → Usuários → Grupos → Organização → Serviço IPM → Billing Account → Serviço BSM → Conta do Cliente
```

### 11.1 Feature `ipm.serviceaccount`
Desproteger e remover a Service Account:
```bash
uv run --project clients/cli sk ipm serviceaccount unprotect --resource-id <SA_ID> --wait
uv run --project clients/cli sk ipm serviceaccount delete --resource-id <SA_ID> --wait
```

### 11.2 Feature `ipm.user`
Desproteger e remover o usuário convidado:
```bash
uv run --project clients/cli sk ipm user unprotect --resource-id <USER_ID> --wait
uv run --project clients/cli sk ipm user delete --resource-id <USER_ID> --wait
```

### 11.3 Feature `ipm.group`
Remover o grupo da organização:
```bash
uv run --project clients/cli sk ipm group delete --resource-id <GROUP_ID>
```

### 11.4 Feature `ipm.organization`
Desproteger e remover a organização (exige estar vazia):
```bash
uv run --project clients/cli sk ipm organization unprotect --resource-id <ORGANIZATION_ID> --wait
uv run --project clients/cli sk ipm organization delete --resource-id <ORGANIZATION_ID> --wait
uv run --project clients/cli sk config unset ipm.organizationId
```

### 11.5 Feature `sum.service` (`ipm`)
Desabilitar o serviço IPM:
```bash
uv run --project clients/cli sk sum service disable --service ipm --wait
```

### 11.6 Features `bsm.account` e `bsm.payment`
Desproteger e remover a Billing Account (exige que não haja organizações atreladas):
```bash
uv run --project clients/cli sk bsm account unprotect --resource-id <BILLING_ACCOUNT_ID> --wait
uv run --project clients/cli sk bsm account delete --resource-id <BILLING_ACCOUNT_ID> --wait
uv run --project clients/cli sk config unset bsm.accountId
```

Se houver Métodos de Pagamento, remova-os depois das Billing Accounts que os referenciam:
```bash
uv run --project clients/cli sk bsm payment unprotect --resource-id <PAYMENT_ID> --wait
uv run --project clients/cli sk bsm payment delete --resource-id <PAYMENT_ID> --wait
```

### 11.7 Feature `sum.service` (`bsm`)
Desabilitar o serviço BSM (exige que não haja Billing Accounts ativas):
```bash
uv run --project clients/cli sk sum service disable --service bsm --wait
```

### 11.8 Feature `cam.account`
Desproteger e excluir definitivamente a conta do cliente:
```bash
uv run --project clients/cli sk cam account unprotect --wait
uv run --project clients/cli sk cam account delete --yes --wait
uv run --project clients/cli sk config unset cam.accountId
```

### 11.9 Sessão
Finalizar a sessão local:
```bash
uv run --project clients/cli sk auth logout
uv run --project clients/cli sk auth whoami
```
*(O comando confirmará que não há mais credenciais ativas).*
