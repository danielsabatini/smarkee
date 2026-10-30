# Guia de Onboarding e Primeiro Acesso com a CLI `sk`

Este documento apresenta o passo a passo completo para cadastrar uma nova conta na plataforma Smarkee, acompanhar a convergência por ticket temporário, ativar o acesso e autenticar via CLI `sk`.

---

## 1. Pré-requisitos do Ambiente de Desenvolvimento

Antes de iniciar, certifique-se de que a stack local ou cluster de desenvolvimento esteja em execução e os domínios mapeados no seu `/etc/hosts`:

```text
127.0.0.1 api-dev.smarkee.com.br ipm-dev.smarkee.com.br mail-dev.smarkee.com.br
```

Carregue as variáveis de ambiente necessárias para a CLI apontar para o gateway local (conforme [`docs/cli/CLI-DEV-STG.md`](CLI-DEV-STG.md)):

```bash
# Na raiz do repositório
source clients/cli/.env
```

---

## 2. Passo a Passo: Do Cadastro ao Primeiro Login

### Passo 1: Solicitar o Cadastro da Conta

Utilize o subcomando `sk account create` informando seu nome, sobrenome e e-mail corporativo.

Por padrão, a CLI adota a flag `--wait`, acompanhando em tempo real a aceitação da solicitação, a reconciliação assíncrona no provedor de identidade (Zitadel) e o envio do e-mail de ativação:

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

Next steps:
  1. Open your inbox and click the link to set your password.
  2. Log in with: `sk auth login`.
```

---

### Passo Alternativo: Cadastro Assíncrono com `--no-wait` e Consulta por Ticket

Se preferir não reter o terminal aguardando a convergência, utilize `--no-wait`. A CLI responderá imediatamente emitindo um **Ticket de Rastreamento** temporário (UUIDv7, válido por 30 minutos):

```bash
uv run --project clients/cli sk account create \
  --name "Ana" \
  --surname "Souza" \
  --email "ana.souza@empresa.com" \
  --no-wait
```

**Saída esperada:**
```text
╭─ ✓ Registration requested ───────────────────────────────────────────────────────╮
│ resourceId          01a18cc9-2bc2-7483-903c-797014939e89                          │
│ registrationTicket  01a18cc9-2bc3-7640-8f92-91e84a20b085                          │
│ expiresAt           2026-10-30T14:30:00Z                                          │
╰───────────────────────────────────────────────────────────────────────────────────╯
Registration ticket: 01a18cc9-2bc3-7640-8f92-91e84a20b085 (valid for 30 minutes)
Use `sk account status --ticket 01a18cc9-2bc3-7640-8f92-91e84a20b085 --wait` to follow up.
```

#### Consultar o Status com `sk account status`:
```bash
uv run --project clients/cli sk account status --ticket 01a18cc9-2bc3-7640-8f92-91e84a20b085
```

**Saída esperada:**
```text
╭─ ✓ Registration status ──────────────────────────────────────────────────────────╮
│ ticket           01a18cc9-2bc3-7640-8f92-91e84a20b085                            │
│ phase            Ready                                                           │
│ email            a***a@empresa.com                                               │
│ emailDispatched  yes                                                             │
│ activated        no                                                              │
│ expiresAt        2026-10-30T14:30:00Z                                            │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

*(Caso precise reenviar o e-mail de ativação, basta rodar com a flag `--resend`:)*
```bash
uv run --project clients/cli sk account status --ticket 01a18cc9-2bc3-7640-8f92-91e84a20b085 --resend
```

---

### Passo 2: Ativar a Conta e Cadastrar a Senha

1. Em desenvolvimento, as mensagens transacionais são capturadas pelo **Mailpit**. Acesse a interface web:
   * **URL:** [http://localhost:8025](http://localhost:8025)
2. Localize a mensagem com assunto de verificação enviada para `ana.souza@empresa.com`.
3. Clique no link **Verificar e-mail** contido no corpo da mensagem.
4. O navegador abrirá a tela do Zitadel (`http://ipm-dev.smarkee.com.br:8080`).
5. Digite e confirme sua nova senha de acesso.
6. A conta passará para o estado verificado e ativo.

---

### Passo 3: Autenticar na CLI

Com a senha cadastrada, efetue o login interativo via fluxo OIDC:

```bash
uv run --project clients/cli sk auth login
```

* O navegador abrirá automaticamente a página de login.
* Entre com o e-mail (`ana.souza@empresa.com`) e a senha definida no passo anterior.
* Confirme a autorização de acesso da aplicação CLI.
* O terminal confirmará o login com sucesso e salvará a sessão de forma segura.

---

### Passo 4: Verificar a Identidade e a Conta

Valide os dados da sessão autenticada:

```bash
uv run --project clients/cli sk auth whoami
```

**Saída esperada:**
```text
╭─ ✓ Authenticated ────────────────────────────────────────────────────────────────╮
│ subject    01a18cc9-2bc2-7483-903c-797014939e89                                  │
│ name       Ana Souza                                                             │
│ email      ana.souza@empresa.com                                                 │
│ issuer     http://ipm-dev.smarkee.com.br:8080                                    │
│ clientId   123456789012345678@smarkee                                            │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

Em seguida, confira os dados do recurso da sua conta na plataforma:

```bash
uv run --project clients/cli sk account get
```

**Saída esperada:**
```text
╭─ ✓ Account ──────────────────────────────────────────────────────────────────────╮
│ resourceId      01a18cc9-2bc2-7483-903c-797014939e89                             │
│ name            Ana Souza                                                        │
│ email           ana.souza@empresa.com                                            │
│ phase           Ready                                                            │
│ platformAccess  granted                                                          │
│ protected       yes                                                              │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

---

## 3. Próximos Passos na Plataforma

Com a conta pronta e a sessão ativa:
* O loop de plataforma provisiona automaticamente uma **Billing Account** inicial gratuita (`"Free Tier"`, decisão `0082`). Consulte com:
  ```bash
  uv run --project clients/cli sk bsm account list
  ```
* Habilite o serviço IPM para sua conta:
  ```bash
  uv run --project clients/cli sk sum service enable --service ipm --wait
  ```
* Crie sua primeira organização:
  ```bash
  uv run --project clients/cli sk ipm organization create --name "minha-empresa" --display-name "Minha Empresa" --wait
  ```
