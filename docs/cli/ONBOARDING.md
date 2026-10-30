# Guia Completo de Onboarding, Operação e Desmonte com a CLI `sk`

Este documento apresenta o roteiro completo de ponta a ponta para validar todas as capacidades da plataforma Smarkee através da CLI `sk`. O roteiro está organizado **por feature** do ecossistema, cobrindo o ciclo de vida completo de cada recurso desde o provisionamento até o desmonte ordenado.

> **Padrão de Execução:** Todos os comandos usam o formato a partir da raiz do repositório (`uv run --project clients/cli sk <comando>`). Se estiver dentro do diretório `clients/cli`, utilize `uv run sk <comando>`.

---

## Índice por Feature

1. [Preparação do Ambiente (`clients/cli`)](#1-preparação-do-ambiente-clientscli)
2. [Feature `core.account` — Onboarding, Identidade e Conta Pessoal](#2-feature-coreaccount--onboarding-identidade-e-conta-pessoal)
3. [Feature `bsm.account` — Unidade de Cobrança (Billing Service Manager)](#3-feature-bsmaccount--unidade-de-cobrança-billing-service-manager)
4. [Feature `sum.service` — Serviços de Plataforma (Service Usage Manager)](#4-feature-sumservice--serviços-de-plataforma-service-usage-manager)
5. [Feature `ipm.organization` — Gestão de Organizações](#5-feature-ipmorganization--gestão-de-organizações)
6. [Features `ipm.permission` e `ipm.role` — Catálogo IAM de Permissões e Roles](#6-features-ipmpermission-e-ipmrole--catálogo-iam-de-permissões-e-roles)
7. [Feature `ipm.group` — Grupos da Organização](#7-feature-ipmgroup--grupos-da-organização)
8. [Feature `ipm.user` — Membros e Usuários da Organização](#8-feature-ipmuser--membros-e-usuários-da-organização)
9. [Feature `ipm.serviceaccount` — Identidades de Máquina (M2M)](#9-feature-ipmserviceaccount--identidades-de-máquina-m2m)
10. [Desmonte Ordenado e Exclusão Total (Hierarquia Reversa)](#10-desmonte-ordenado-e-exclusão-total-hierarquia-reversa)

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

## 2. Feature `core.account` — Onboarding, Identidade e Conta Pessoal

O módulo `core.account` gerencia o ciclo de vida da conta pessoal e do usuário raiz no provedor de identidade (Zitadel).

### 2.1 Auto-cadastro Síncrono (`--wait`, padrão)
Solicite o cadastro da conta. Por padrão, a CLI adota `--wait`, aguardando a criação assíncrona no provedor e o envio do e-mail de ativação:

```bash
uv run --project clients/cli sk account create \
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
uv run --project clients/cli sk account create \
  --name "Ana" \
  --surname "Souza" \
  --email "ana.souza@empresa.com" \
  --no-wait
```

#### Consultar o Status por Ticket:
```bash
uv run --project clients/cli sk account status --ticket <TICKET_UUID>
```

#### Solicitar Reenvio de E-mail de Ativação (com Rate Limiting de 60s):
```bash
uv run --project clients/cli sk account status --ticket <TICKET_UUID> --resend
```

### 2.3 Ativação no Mailpit e Cadastro de Senha
1. Abra a caixa de entrada no **Mailpit**: [http://localhost:8025](http://localhost:8025)
2. Abra o e-mail de verificação enviado para `ana.souza@empresa.com`.
3. Clique em **Verificar e-mail**.
4. Na tela do Zitadel (`http://ipm-dev.smarkee.com.br:8080`), cadastre uma senha inicial (ex: `SenhaSegura@123`).

### 2.4 Login OIDC e Inspeção da Conta Pessoal
Autentique-se via navegador e confira os dados da sessão:

```bash
# Efetuar o login OIDC (abre o navegador)
uv run --project clients/cli sk auth login

# Verificar a sessão ativa
uv run --project clients/cli sk auth whoami

# Inspecionar os detalhes da sua conta pessoal
uv run --project clients/cli sk account get
```

---

## 3. Feature `bsm.account` — Unidade de Cobrança (Billing Service Manager)

O módulo `bsm.account` gerencia as unidades de faturamento e limites de cobrança. Conforme a arquitetura de recursos internos (`internal-state`, decisões `0098` e `0100`), a criação de uma Billing Account é realizada explicitamente via CLI:

```bash
# Criar uma Billing Account inicial
uv run --project clients/cli sk bsm account create \
  --display-name "Free Tier" \
  --currency BRL \
  --contact ana.souza@empresa.com \
  --wait
```

**Saída esperada:**
```text
waiting: request accepted (0 s of 60 s)
waiting: provisioning (ready) (0 s of 60 s)
╭─ ✓ Billing Account created ──────────────────────────────────────────────────────╮
│ displayName      Free Tier                                                       │
│ currency         BRL                                                             │
│ resourceId       01a18cc9-7970-7483-903c-2bc214939e89                            │
│ phase            Ready                                                           │
│ protected        yes                                                             │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

Em seguida, liste as contas, inspecione seus detalhes e fixe-a como padrão na configuração local da CLI:

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

## 4. Feature `sum.service` — Serviços de Plataforma (Service Usage Manager)

O módulo `sum.service` gerencia a habilitação de serviços da plataforma para o solicitante.

```bash
# Listar o catálogo de serviços
uv run --project clients/cli sk sum service list

# Habilitar o serviço IPM (Identity Provider Manager) aguardando convergência
uv run --project clients/cli sk sum service enable --service ipm --wait

# Conferir o estado observado do serviço habilitado
uv run --project clients/cli sk sum service get --service ipm
```

---

## 5. Feature `ipm.organization` — Gestão de Organizações

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

## 6. Features `ipm.permission` e `ipm.role` — Catálogo IAM de Permissões e Roles

As features `ipm.permission` e `ipm.role` controlam o catálogo de permissões atômicas e roles compostas pré-definidas no padrão Google Cloud IAM.

```bash
# Listar as permissões atômicas registradas no catálogo da plataforma
uv run --project clients/cli sk ipm permission list

# Listar as roles compostas disponíveis (ex: ipm.organizationAdmin, ipm.organizationViewer)
uv run --project clients/cli sk ipm role list
```

---

## 7. Feature `ipm.group` — Grupos da Organização

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

## 8. Feature `ipm.user` — Membros e Usuários da Organização

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

## 9. Feature `ipm.serviceaccount` — Identidades de Máquina (M2M)

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

## 10. Desmonte Ordenado e Exclusão Total (Hierarquia Reversa)

A plataforma impõe proteção contra exclusão acidental e exige a **remoção hierárquica inversa**: recursos filhos devem ser removidos antes dos contêineres e serviços atrelados.

```text
Service Accounts → Usuários → Grupos → Organização → Serviços SUM → Billing Account → Conta Pessoal
```

### 10.1 Feature `ipm.serviceaccount`
Desproteger e remover a Service Account:
```bash
uv run --project clients/cli sk ipm serviceaccount unprotect --resource-id <SA_ID> --wait
uv run --project clients/cli sk ipm serviceaccount delete --resource-id <SA_ID> --wait
```

### 10.2 Feature `ipm.user`
Desproteger e remover o usuário convidado:
```bash
uv run --project clients/cli sk ipm user unprotect --resource-id <USER_ID> --wait
uv run --project clients/cli sk ipm user delete --resource-id <USER_ID> --wait
```

### 10.3 Feature `ipm.group`
Remover o grupo da organização:
```bash
uv run --project clients/cli sk ipm group delete --resource-id <GROUP_ID>
```

### 10.4 Feature `ipm.organization`
Desproteger e remover a organização (exige estar vazia):
```bash
uv run --project clients/cli sk ipm organization unprotect --resource-id <ORGANIZATION_ID> --wait
uv run --project clients/cli sk ipm organization delete --resource-id <ORGANIZATION_ID> --wait
uv run --project clients/cli sk config unset ipm.organizationId
```

### 10.5 Feature `sum.service`
Desabilitar o serviço IPM:
```bash
uv run --project clients/cli sk sum service disable --service ipm --wait
```

### 10.6 Feature `bsm.account`
Desproteger e remover a Billing Account (exige que não haja organizações atreladas):
```bash
uv run --project clients/cli sk bsm account unprotect --resource-id <BILLING_ACCOUNT_ID> --wait
uv run --project clients/cli sk bsm account delete --resource-id <BILLING_ACCOUNT_ID> --wait
uv run --project clients/cli sk config unset bsm.accountId
```

### 10.7 Feature `core.account`
Desproteger e excluir definitivamente a conta pessoal:
```bash
uv run --project clients/cli sk account unprotect --wait
uv run --project clients/cli sk account delete --yes --wait
```

### 10.8 Sessão
Finalizar a sessão local:
```bash
uv run --project clients/cli sk auth logout
uv run --project clients/cli sk auth whoami
```
*(O comando confirmará que não há mais credenciais ativas).*
