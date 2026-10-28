# Infraestrutura de desenvolvimento

Ambiente local em Docker Compose. **Somente para desenvolvimento**: as credenciais são triviais e as portas ficam presas a `127.0.0.1`, acessíveis apenas na própria máquina.

## Primeira vez: arquivos `.env` e `/etc/hosts`

### 1. Resolução de DNS local (`/etc/hosts`)

O gateway roteia por host: atende o Zitadel em `ipm-dev.smarkee.com.br` e a API da plataforma em `api-dev.smarkee.com.br`. Adicione os apontamentos para o loopback no seu arquivo `/etc/hosts`:

```bash
echo "127.0.0.1 ipm-dev.smarkee.com.br api-dev.smarkee.com.br" | sudo tee -a /etc/hosts
```

### 2. Criação dos arquivos `.env`

Cada serviço lê o seu `.env` (fora do git), criado a partir do exemplo:

```bash
for s in database messaging identity gateway; do cp -n $s/.env.example $s/.env; done
```

Preencha os valores obrigatórios (vazios no exemplo) antes de subir:

| Arquivo | Variável | Valor |
|---|---|---|
| `database/.env` | `SMARKEE_DATABASE_PASSWORD` | Senha do administrador `postgres`: `openssl rand -hex 16` |
| `gateway/.env` | `SMARKEE_GATEWAY_ADMIN_KEY` | Chave da Admin API e do console web do gateway: `openssl rand -hex 16` |
| `gateway/.env` | `SMARKEE_GATEWAY_AUTH_AUDIENCE_CORE_ACCOUNT`, `SMARKEE_GATEWAY_AUTH_AUDIENCE_IPM_ORGANIZATION`, `SMARKEE_GATEWAY_AUTH_AUDIENCE_IPM_SERVICEACCOUNT`, `SMARKEE_GATEWAY_AUTH_AUDIENCE_IPM_USER`, `SMARKEE_GATEWAY_AUTH_AUDIENCE_SUM_SERVICE` | Depois de provisionar o Zitadel: o ID do projeto de roles de cada módulo, o mesmo `*_AUTH_AUDIENCE` do Receiver correspondente. Vazios, o gateway rejeita todo token nessa API (falha fechada); aplique com `docker compose up -d gateway-sync` |
| `messaging/.env` | `SMARKEE_MESSAGING_PASSWORD` | Senha do usuário do NATS: `openssl rand -hex 16` |
| `identity/.env` | `SMARKEE_IDENTITY_MASTERKEY` | Exatamente 32 caracteres: `openssl rand -hex 16`. Não altere depois da primeira subida |
| `identity/.env` | `SMARKEE_IDENTITY_ADMIN_PASSWORD` | Senha inicial do administrador do Zitadel, com maiúscula, minúscula, número e símbolo |
| `identity/.env` | `SMARKEE_IDENTITY_SESSION_COOKIE_SECRET` | `openssl rand -hex 32` |
| `features/core/account/.env` | `CORE_ACCOUNT_<PAPEL>_MESSAGING_PASSWORD` (`RECEIVER`, `MANAGER`, `PUBLISHER`, `RECONCILER`, `OBSERVER`, `EXECUTOR`) | A mesma `SMARKEE_MESSAGING_PASSWORD` de `messaging/.env` |
| `features/ipm/organization/.env` | `IPM_ORGANIZATION_<PAPEL>_MESSAGING_PASSWORD` (`PUBLISHER`, `CONTROLLER`) | A mesma `SMARKEE_MESSAGING_PASSWORD` de `messaging/.env` |
| `features/ipm/permission/.env` | `IPM_PERMISSION_<PAPEL>_MESSAGING_PASSWORD` (`API`, `PUBLISHER`, `CONTROLLER`) e `IPM_PERMISSION_API_AUTH_AUDIENCE` | A mesma `SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`; o ID do projeto `roles-ipm` na audience (decisão 0098) |
| `features/ipm/serviceaccount/.env` | `IPM_SERVICEACCOUNT_<PAPEL>_MESSAGING_PASSWORD` (`api`, `publisher` e `controller`), `IPM_SERVICEACCOUNT_API_AUTH_AUDIENCE` e `IPM_SERVICEACCOUNT_IDENTITY_PROJECT_ID` | A mesma `SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`; o ID do projeto `roles-ipm` nas duas outras (decisão 0094) |
| `features/ipm/user/.env` | `IPM_USER_<PAPEL>_MESSAGING_PASSWORD` (os seis papéis), `IPM_USER_RECEIVER_AUTH_AUDIENCE` e `IPM_USER_IDENTITY_PROJECT_ID` | A mesma `SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`; o ID do projeto `roles-ipm` nas duas outras (decisão 0077) |
| `features/core/account/.env` e `features/ipm/organization/.env` | `CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE`, `IPM_ORGANIZATION_API_AUTH_AUDIENCE` | ID do projeto de roles do módulo no Zitadel (organização `core`): `roles-core` para a Account, `roles-ipm` para a Organization (decisão 0032) |

Os componentes das features (Account e Organization) **não são subidos por este diretório**: cada feature tem o seu `compose.yaml` e o seu `.env` (`cp .env.example .env` em `features/core/account` e `features/ipm/organization`), e eles esperam a plataforma abaixo no ar. Suba a plataforma primeiro e depois cada feature (`docker compose up -d --build` na pasta dela). Se recriar o Receiver de uma feature, o `gateway` volta a resolver o endereço sozinho em poucos segundos; não é preciso reiniciá-lo.

Nas features, as senhas dos papéis do `.env` chegam aos contêineres como arquivos em `/run/secrets/<VARIÁVEL>`, e não como variáveis de ambiente (decisão [`0070`](../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md)). Edite o `.env` e recrie os contêineres (`docker compose up -d`).

Variáveis adicionais configuradas no `identity/.env`:
- `SMARKEE_IDENTITY_INSTANCE_NAME`: Nome da instância exibido no console (padrão: `IPM`).
- `SMARKEE_IDENTITY_ORG_NAME`: Nome da organização inicial (padrão: `smarkee.internal`).
- `SMARKEE_IDENTITY_ADMIN_USERNAME`: Nome do usuário administrador (padrão: `admin`).
- `SMARKEE_IDENTITY_ADMIN_EMAIL`: E-mail do administrador (padrão: `admin@smarkee.internal`).
- `SMARKEE_IDENTITY_EXTERNAL_DOMAIN`: Domínio público de acesso (padrão: `ipm-dev.smarkee.com.br`).
- `SMARKEE_IDENTITY_EXTERNAL_PORT`: Porta pública de acesso (padrão: `8080`, igual a `SMARKEE_GATEWAY_PROXY_HTTP_PORT`).

No `gateway/.env`, só `SMARKEE_GATEWAY_ADMIN_KEY` é obrigatória para subir (`SMARKEE_GATEWAY_PROXY_HTTP_PORT=8080` e `SMARKEE_GATEWAY_ADMIN_PORT=9180` por padrão); as `SMARKEE_GATEWAY_AUTH_AUDIENCE_*` só existem depois do Zitadel provisionado.

## E-mail de desenvolvimento (Mailpit)

O serviço `mail` captura o SMTP do Zitadel (`mail.smarkee.internal:1025`, só na rede `internal`); nada sai da máquina. A interface web fica em http://localhost:8025 (somente no host) e mostra os e-mails de ativação e de redefinição de senha.

- **Instância nova:** o `identity/compose.yaml` já aponta o Zitadel para o Mailpit (`ZITADEL_DEFAULTINSTANCE_SMTPCONFIGURATION_*`, aplicado só na primeira inicialização).
- **Instância existente:** a configuração SMTP é da instância, e não de variável. Aplique pela Admin API ou pelo console (**Configurações → SMTP**): host `mail.smarkee.internal:1025`, sem TLS, remetente `ipm-dev@smarkee.internal` e nome `IPM-DEV`. Há um e-mail de teste no console.
- **Destinatário:** o Mailpit só captura; **ninguém recebe** os e-mails, e por isso testes com `example.com` são seguros. Para enviar de verdade em dev, troque a configuração SMTP ativa para um provedor real (por exemplo, o Brevo) no console, sem versionar a chave, e volte ao Mailpit depois: só uma configuração fica ativa por instância. Em stg e prd o SMTP é sempre o provedor real.

## Subir e derrubar

```bash
docker compose up -d                                                 # sobe tudo, inclusive os contêineres de inicialização
docker compose up -d --wait messaging gateway identity identity-login mail   # espera os serviços de longa duração ficarem saudáveis
docker compose ps                                                    # estado e saúde
docker compose down              # derruba, preservando os volumes
docker compose down -v           # derruba e APAGA os dados
```

Antes de apagar os dados, faça o backup: `scripts/dev/backup` (`uv run smarkee-dev-backup reset --apply` faz o backup, prova que ele restaura e só então zera o ambiente). Configurações feitas direto no Zitadel vivem só nos volumes; o gateway se reconstrói a partir de `gateway/bootstrap/adc.yaml`.

Os contêineres de inicialização permanecem parados (`Exited (0)`) depois de executar, preservando o código de saída e os logs para diagnóstico (`docker compose ps -a`, `docker compose logs <serviço>`). O Compose não os remove automaticamente: não há equivalente ao `docker run --rm`, e o `depends_on: service_completed_successfully` precisa do contêiner encerrado para ler o código de saída. A próxima subida os recria.

Cada serviço também sobe isoladamente em seu próprio diretório (`cd database && docker compose up -d`). Use **um modo por vez**: os nomes dos containers são fixos e conflitam entre os dois modos. Cada recurso tem um único `compose.yaml`. O `identity` inclui o `database/compose.yaml`: isolado, sobe o PostgreSQL junto e aguarda que ele aceite conexões.

## Como acessar

Com a stack de pé (`docker compose ps`) e o `/etc/hosts` configurado:

| O que | Endereço | Credencial |
|---|---|---|
| Console do Zitadel | http://ipm-dev.smarkee.com.br:8080/ui/console/ | Usuário `admin@smarkee.internal` (ou `admin@smarkee.ipm-dev.smarkee.com.br`) e a senha `SMARKEE_IDENTITY_ADMIN_PASSWORD` de `identity/.env` (troca obrigatória no primeiro acesso) |
| Cadastro de nova organização (Zitadel) | http://ipm-dev.smarkee.com.br:8080/ui/login/register/org | **Desligado** (decisão 0013): o cadastro público foi desativado na política de login; usuários e organizações nascem pelo Receiver |
| API da plataforma | http://api-dev.smarkee.com.br:8080/v1/ | Token do `sk auth login` (`Authorization: Bearer`), validado já no gateway (decisão 0052); o cadastro (`POST /v1/core/accounts`) é anônimo, com limite de taxa |
| Console web do gateway (APISIX) | http://localhost:9180/ui | `SMARKEE_GATEWAY_ADMIN_KEY` de `gateway/.env` (digitada no login do console) |
| Admin API do gateway | http://localhost:9180/apisix/admin | Cabeçalho `X-API-KEY` com a mesma chave |
| PostgreSQL | `psql "postgresql://ssot:ssot@localhost:5432/ssot"` | Ver "Credenciais" |
| NATS | `nats://smarkee:<SMARKEE_MESSAGING_PASSWORD>@localhost:4222` · monitoramento em http://localhost:8222 | `SMARKEE_MESSAGING_PASSWORD` de `messaging/.env` |

- Use o nome `ipm-dev.smarkee.com.br` **com a porta `:8080`** no navegador. O endereço `localhost:8080` não é roteado (o gateway roteia por host) e responde 404.
- De um contêiner na rede `internal`, use os nomes `*.smarkee.internal` da coluna **Rede `internal`** do mapa abaixo; `localhost` ali aponta para o próprio contêiner.
- Todas as portas são publicadas apenas em `127.0.0.1`.
- **Nome de login no Zitadel:** informe o nome completo, `usuário@domínio-da-organização`, ou o e-mail do usuário. Digitar só `admin` retorna "usuário não encontrado". Para o administrador: `admin@smarkee.internal` ou `admin@smarkee.ipm-dev.smarkee.com.br`. O domínio de uma organização é `<nome-da-organização>.ipm-dev.smarkee.com.br` (por exemplo, `core.ipm-dev.smarkee.com.br`, confirmado no token); o e-mail do usuário também funciona.
- O cadastro público do Zitadel (usuário e organização) está **desligado**: usuários e organizações nascem pela API da plataforma (decisões 0013 e 0014). A porta faz parte do endereço (`SMARKEE_IDENTITY_EXTERNAL_PORT`); em outros ambientes o endereço será outro.

## Mapa de acesso

Do host, use a coluna **Host**. De um container na rede `internal` (por exemplo, um serviço do projeto rodando em Docker), use a coluna **Rede `internal`**: dentro de um container, `localhost` e `*.localhost` apontam para o próprio container.

| Sistema | Host | Rede `internal` | Observação |
|---|---|---|---|
| Zitadel (console) | http://ipm-dev.smarkee.com.br:8080/ui/console/ | — | Navegador, via gateway |
| Zitadel (login) | http://ipm-dev.smarkee.com.br:8080/ui/v2/login/ | — | Navegador, via gateway |
| Zitadel (OIDC e APIs) | http://ipm-dev.smarkee.com.br:8080 | http://gateway.smarkee.internal:8000 com o cabeçalho `Host: ipm-dev.smarkee.com.br:8080` | Ver a seção OIDC |
| Zitadel API (direto, sem gateway) | — (porta não publicada) | http://identity.smarkee.internal:8080 com o cabeçalho `Host: ipm-dev.smarkee.com.br:8080` | Chamadas entre serviços e diagnóstico; sem o cabeçalho responde 404 |
| Zitadel login (direto, sem gateway) | — (porta não publicada) | http://identity-login.smarkee.internal:3000/ui/v2/login/ | Somente diagnóstico (`/ui/v2/login/healthy`) |
| Gateway, proxy HTTP (APISIX) | http://ipm-dev.smarkee.com.br:8080 | http://gateway.smarkee.internal:8000 | Roteia por host (`gateway/bootstrap/adc.yaml`); host desconhecido responde 404 |
| API de Account (`core`) | http://api-dev.smarkee.com.br:8080/v1/core/accounts (só `/v1/core/accounts`) | http://core-account-api.smarkee.internal:8000 | `/health/*` só na rede interna. O cadastro anônimo (`POST /v1/core/accounts`) tem limite de 10 por minuto por IP no gateway (rota `core-account-register`) e de 5 por 60 s por origem na API |
| API de Organization (`ipm`, decisão 0098) | http://api-dev.smarkee.com.br:8080/v1/ipm/organizations (só `/v1/ipm/organizations`) | http://ipm-organization-api.smarkee.internal:8000 | `/health/live`, `/health/ready` e `/health/startup`, só na rede interna |
| Receiver de User (`ipm`) | http://api-dev.smarkee.com.br:8080/v1/ipm/users (só `/v1/ipm/users`) | http://ipm-user-receiver.smarkee.internal:8000 | `/health/*` só na rede interna. Consulta o Receiver de Organization (e é consultado por ele) na rede interna, com o token de quem pede |
| API de ServiceAccount (`ipm`, decisão 0098) | http://api-dev.smarkee.com.br:8080/v1/ipm/serviceaccounts (só `/v1/ipm/serviceaccounts`) | http://ipm-serviceaccount-api.smarkee.internal:8000 | `/health/*` só na rede interna. Consulta o Receiver de Organization e é consultado por User, Group, Role e Organization na rede interna, com o token de quem pede (decisão 0094) |
| Gateway, Admin API e console web (`/ui`) | http://localhost:9180 | http://gateway.smarkee.internal:9180 | Chave `SMARKEE_GATEWAY_ADMIN_KEY` obrigatória (cabeçalho `X-API-KEY`); qualquer contêiner da rede `internal` a alcança |
| Roteador da telemetria (`telemetry-router`) | — (sem porta no host) | `telemetry-router.smarkee.internal`: OTLP HTTP `4318`, gRPC `4317`, saúde `13133` | **Só roteia, não grava em backend** (decisão 0062): recebe do agente e do gateway de borda (`SMARKEE_GATEWAY_TELEMETRY_ADDRESS`), ajusta os spans do APISIX à semconv (decisão 0050) e envia cada sinal ao telemeter dono (logs por módulo e tipo, spans por `apisix.service_name`), com fila em disco (`telemetry-router/data/`). Função em `telemetry-router/README.md` |
| Telemeter da plataforma (`platform-telemeter`) | — (sem porta no host) | `platform-telemeter.smarkee.internal`: OTLP gRPC `4317`, saúde `13133` | **Processa e grava** a **infra** e o app que não tem telemeter próprio: separa infra e app e grava `platform-telemeter/logs/{app,infra}`, `metrics/{app,infra}` e `traces/` (exporter `file`, rotação em 10 MB; decisão 0053). Função em `platform-telemeter/README.md` |
| Telemeter de uma feature (`<módulo>-<tipo>-telemeter`) | — (sem porta no host) | `core-account-telemeter.smarkee.internal` (e `ipm-organization-…`, `ipm-serviceaccount-…`, `ipm-user-…`, `sum-service-…`): OTLP gRPC `4317`, saúde `13133` | **Processa e grava** os sinais de **app** da feature (logs e spans), sem privilégios: aplica a política da feature e grava em `features/core/account/telemeter/{logs,traces}/`. Vive no `compose.yaml` da feature; função em `features/core/account/telemeter/README.md` (decisão 0062) |
| Agente de telemetria (`telemetry-agent`) | — (sem porta no host) | `telemetry-agent.smarkee.internal` | **Lê** as métricas de contêiner (`docker_stats`) e os logs JSON dos componentes (`json-file`) e envia por OTLP/gRPC ao `telemetry-router` (`SMARKEE_TELEMETRY_ROUTER_ENDPOINT`, porta `4317`); é o único leitor privilegiado e não conhece as features (decisões 0051 e 0062). Monta o socket do Docker e roda como root: só para dev |
| etcd do gateway | — (não publicado) | http://gateway-etcd.smarkee.internal:2379 | Guarda a configuração do APISIX; sem autenticação (dev) |
| PostgreSQL | `localhost:5432` | `database.smarkee.internal:5432` | Senha obrigatória por TCP (SCRAM) |
| NATS (cliente) | `nats://localhost:4222` | `nats://messaging.smarkee.internal:4222` | Usuário e senha obrigatórios |
| NATS (monitoramento) | http://localhost:8222 | http://messaging.smarkee.internal:8222 | `/healthz`, `/varz`, `/jsz`; sem autenticação |

O gateway trata somente HTTP (sem HTTPS em dev) e roteia por host: o Zitadel atende `ipm-dev.smarkee.com.br`, e cada novo Receiver recebe um host próprio (por exemplo, `api.localhost`). No host, aponte `127.0.0.1 ipm-dev.smarkee.com.br` em `/etc/hosts`. O NATS e o PostgreSQL são acessados diretamente, sem o gateway.

O proxy HTTP do gateway é publicado na porta 8080 do host (no container, continua na 8000). A porta 80 não é usada porque costuma estar ocupada por outros serviços locais (por exemplo, ingress de clusters Kubernetes locais). O `SMARKEE_IDENTITY_EXTERNAL_PORT` precisa ser igual à porta publicada do proxy (ver pontos de atenção).

Somente o gateway publica portas do Zitadel. O acesso direto ao `identity` e ao `identity-login` existe apenas na rede `internal`, e o Zitadel escolhe a instância pelo domínio, por isso o cabeçalho `Host` é obrigatório e **deve incluir a porta** (`Host: ipm-dev.smarkee.com.br:8080`): sem a porta, o issuer devolvido perde o `:8080` e não confere com o dos tokens emitidos pelo navegador. O navegador (console e login) deve sempre passar pelo gateway: os redirecionamentos e o issuer apontam para `http://ipm-dev.smarkee.com.br:8080`, e só o gateway reúne o Receiver e o login no mesmo domínio.

## Credenciais

Valores sensíveis ficam nos arquivos `.env` (fora do git). As senhas dos bancos de aplicação são triviais e fixas em `database/bootstrap/*.sql`.

| Sistema | Usuário | Senha | Onde está |
|---|---|---|---|
| Zitadel (administrador) | `admin@smarkee.internal` ou `admin@smarkee.ipm-dev.smarkee.com.br` | `SMARKEE_IDENTITY_ADMIN_PASSWORD` | `identity/.env` (troca obrigatória no primeiro acesso) |
| PostgreSQL (administrador) | `postgres` | `SMARKEE_DATABASE_PASSWORD` | `database/.env` |
| PostgreSQL, banco `ssot` (SSOT, proprietário) | `ssot` | `ssot` | `database/bootstrap/ssot.sql` |
| PostgreSQL, banco `identity` | `identity` | `identity` | `database/bootstrap/identity.sql` (o Zitadel usa só este usuário, sem credencial de administrador) |
| PostgreSQL, banco `ssot` (módulo `core`, Account) | `core_account_api_login`, `core_account_controller_login`, `core_account_publisher_login`, `core_maintenance_login` | igual ao usuário | `database/bootstrap/core.sql` |
| PostgreSQL, banco `ssot` (módulo `ipm`, Organization) | `ipm_organization_api_login`, `ipm_organization_publisher_login`, `ipm_maintenance_login` | igual ao usuário | `database/bootstrap/ipm.sql` |
| PostgreSQL, banco `ssot` (módulo `ipm`, User) | `ipm_user_manager_login`, `ipm_user_receiver_login`, `ipm_user_publisher_login` | igual ao usuário | `database/bootstrap/ipm.sql` |
| PostgreSQL, banco `ssot` (módulo `ipm`, ServiceAccount) | `ipm_serviceaccount_api_login`, `ipm_serviceaccount_publisher_login`, `ipm_serviceaccount_controller_login` | igual ao usuário | `database/bootstrap/ipm.sql` |
| NATS | `SMARKEE_MESSAGING_USER` (`smarkee`) | `SMARKEE_MESSAGING_PASSWORD` | `messaging/.env` (um único usuário em dev, compartilhado pelos serviços) |
| Gateway (APISIX), Admin API e console web | — | `SMARKEE_GATEWAY_ADMIN_KEY` | `gateway/.env` (chave obrigatória, sem padrão) |

O usuário `ssot` é o proprietário do SSOT, destinado a migrações (`docs/data/POSTGRESQL.md`). Cada serviço usa um papel de login próprio, membro de um papel de função sem login (`docs/data/POSTGRESQL.md` §14.2 e §14.3). Criar papéis exige `CREATEROLE`, que o `smarkee` não tem: os papéis são criados como administrador em `database/bootstrap/<módulo>.sql`, e os privilégios são concedidos pela migração do módulo.

## Strings de conexão

| Destino | Do host | Da rede `internal` |
|---|---|---|
| SSOT (proprietário) | `postgresql://ssot:ssot@localhost:5432/ssot` | `postgresql://ssot:ssot@database.smarkee.internal:5432/ssot` |
| NATS | `nats://smarkee:<SMARKEE_MESSAGING_PASSWORD>@localhost:4222` | `nats://smarkee:<SMARKEE_MESSAGING_PASSWORD>@messaging.smarkee.internal:4222` |

Não há TLS em dev (`sslmode=disable` quando o cliente exigir o parâmetro).

## OIDC (Zitadel)

| Item | Valor |
|---|---|
| Issuer | `http://ipm-dev.smarkee.com.br:8080` |
| Discovery | `http://ipm-dev.smarkee.com.br:8080/.well-known/openid-configuration` |
| JWKS | `http://ipm-dev.smarkee.com.br:8080/oauth/v2/keys` |
| Autorização / token | `http://ipm-dev.smarkee.com.br:8080/oauth/v2/authorize` · `/oauth/v2/token` |

- Use sempre o endereço HTTP da porta 8080 (`http://ipm-dev.smarkee.com.br:8080`). O issuer é derivado do endereço de acesso (inclusive o esquema e a porta), e tokens emitidos por um endereço não validam no outro.
- Um serviço em container obtém o discovery e o JWKS por `http://gateway.smarkee.internal:8000` ou, sem o gateway, por `http://identity.smarkee.internal:8080`, em ambos os casos com o cabeçalho `Host: ipm-dev.smarkee.com.br:8080`, e valida o `iss` contra `http://ipm-dev.smarkee.com.br:8080`.

### Configuração do Zitadel para a plataforma (`sk auth login`)

O `sk` autentica direto no Zitadel, pelo gateway, sem API própria de autenticação (Authorization Code com PKCE e retorno em `127.0.0.1`; uso em `clients/cli/README.md`). Ele usa a sua aplicação nativa, que fica no projeto `clients` (sem roles). Pelas decisões 0010, 0013, 0014, 0032 e 0034, o desenho é:

| Organização | Papel |
|---|---|
| `smarkee` | Só operadores e contas administrativas da instância (`admin`, `platform-bootstrap`, `login-client`). Não tem recursos da plataforma |
| `core` | Organização de sistema da plataforma: dona dos projetos de roles (`roles-core`, `roles-ipm`, `roles-sum`) e do projeto `clients` (aplicações dos clientes da plataforma). Sem usuários cadastrados e sem papéis das contas de serviço |
| `register` | Usuários cadastrados (decisões 0026 e 0027). Recebe cada projeto de roles por Project Grant (só as roles de ação, sem as `*.admin`) |

Estado aplicado no dev em 2026-10-10 (pela API do Zitadel, com a conta de bootstrap; o script usado é temporário e não versionado):

- **Um projeto de roles por módulo, na organização `core`** (decisão 0032): `roles-core`, `roles-ipm` e `roles-sum`. Em cada um, roles no token e **verificação de role na autenticação** ligadas. Cada módulo tem o seu projeto para que o Project Grant (que é por projeto) limite o que cada Executor concede.
- **Roles por ação:** `core.account.get|delete` (`roles-core`), `ipm.organization.create|delete|get|list|update` e `ipm.user.create|get|list|update|delete|bind` (`roles-ipm`) e `sum.ipm.enable|disable|get` (`roles-sum`); para operadores, `core.account.admin` (`roles-core`), `ipm.organization.admin` e `ipm.user.admin` (`roles-ipm`), que ficam fora dos Grants. Padrão `<módulo>.<tipo>.<ação>` (decisão 0028); no Zitadel cada role tem o módulo como `group` e um nome de exibição que descreve a ação em pt-BR, nunca a própria key (por exemplo, `ipm.user.get` → "Ler usuários da Organization", `core.account.admin` → "Operador: qualquer conta"). A suíte de conformidade confere.
- **Projeto `clients`** (decisão 0034), na `core`: sem roles, sem Project Grant, roles no token ligadas e **verificação de role na autenticação desligada**. Existe porque, no login interativo, o Zitadel só põe no token as roles do projeto da aplicação: com a `cli` num projeto de roles, o token não valeria nos Receivers dos outros módulos. O `sk` pede a audience de cada módulo (`[core] projectId` e `[sum] projectId`).
- **Aplicação `cli`**, no projeto `clients`: nativa, PKCE, redirect `http://127.0.0.1/callback`, Authorization Code e Refresh Token, **access token JWT**, roles no token. Não há client secret: o `sk` é um cliente público. O client ID é um por ambiente.
- **Cadastro público desligado** na política de login da instância (`allowRegister = false`), que as organizações herdam.
- **Service accounts na organização `core`** (verificadas no Zitadel de dev em 2026-10-11): `core-account-controller` (decisões 0096 e 0098: `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na organização `register`, para criar, remover e ler usuários sem conceder roles; e `PROJECT_GRANT_OWNER` só nos Grants de `roles-core` e `roles-sum`: concede as roles desses módulos, nunca as de `ipm`), sem papel na `core`, com a chave no volume `identity-bootstrap`. As contas antigas `core-account-executor` e `core-account-observer` ficam sem uso (lacuna declarada, `docs/platform/IMPLEMENTATION-STATUS.md`).
- **Service accounts da Organization na organização `core`** (decisão 0038, criadas e renomeadas em 2026-10-16): `ipm-organization-executor` (papel de **instância** `IAM_ORG_MANAGER`: cria, renomeia, ativa, desativa e remove organizações; era `core-organization-executor`, renomeada com o mesmo ID e a mesma chave) e `ipm-organization-observer` (papel de **instância** `IAM_OWNER_VIEWER`, somente leitura, usado para listar organizações). Sem papel na `core` nem na `register`; chaves no volume `identity-bootstrap` (dono 10001, modo 0400), cada componente montando só a própria, e vencem em 2030-01-01. Os dois papéis são de instância e mais largos que o necessário; ficam assim por exceção deliberada, porque o Zitadel não tem papel padrão menor (decisão 0060). A conta `ipm-organization-controller` (papel de instância `IAM_ORG_MANAGER`, chave que vence em 2027-10-21; decisão 0096) substitui as duas: lê e escreve, e é a única identidade de provedor do Controller. Criada em 2026-10-27 pelo operador (platform-bootstrap).
- **Service accounts do User na organização `core`** (decisão 0077, criadas em 2026-10-21): `ipm-user-controller` (decisão 0096, criada em 2026-10-27, que reúne os papéis das duas seguintes), `ipm-user-executor` e `ipm-user-observer`, **sem papel** na `core`, na `register` nem na instância. Os papéis delas são dados pelo operador **em cada organização de cliente** (abaixo, "Preparar uma Organization para usuários"). Chaves no volume `identity-bootstrap` (dono 10001, modo 0400), cada componente montando só a própria; vencem em 2027-10-21.
- **Service accounts do ServiceAccount na organização `core`** (decisão 0094): `ipm-serviceaccount-controller` (decisão 0096, que reúne os papéis das duas seguintes), `ipm-serviceaccount-executor` e `ipm-serviceaccount-observer`, **sem papel** na `core`, na `register` nem na instância, como as do User; os papéis vêm em cada organização de cliente pelo loop da Organization (abaixo). Token Bearer; chaves no volume `identity-bootstrap` (dono 10001, modo 0400), cada componente montando só a própria. **Criação manual** pelo operador (a suíte de conformidade só lê): `POST /v2/users/new` machine na `core`, chave JSON e arquivo `service-account-ipm-serviceaccount-<papel>.json` no volume, como as do User.
- **Service accounts do SUM na organização `core`** (criadas em 2026-10-15; decisões 0096 e 0098): `sum-service-controller` (`ORG_OWNER_VIEWER` só na `register`, para ler o usuário dono; e `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm` para a `register`, para conceder e revogar as permissões do serviço), sem papel na `core`, com a chave no volume `identity-bootstrap` (dono 10001, modo 0400); **criação manual** pelo operador (arquivo `service-account-sum-service-controller.json`). As antigas `sum-service-executor` e `sum-service-observer` ficam sem uso (lacuna declarada, `docs/platform/IMPLEMENTATION-STATUS.md`). As chaves vencem em 2027-10-15: a rotação é a seção "Rotação das chaves das contas de serviço", e a suíte de conformidade avisa 90 dias antes.
- **Service accounts de `ipm/permission`** (decisão 0084, corrigida em 2026-10-26): `ipm-permission-controller` (decisão 0096, criada em 2026-10-27 pelo operador; `PROJECT_OWNER` nos projetos `roles-<módulo>` e `roles-operator` **e** `ORG_OWNER_VIEWER` nas organizações `core` e `operator`; chave que vence em 2027-10-21) reúne os papéis de `ipm-permission-executor` (`PROJECT_OWNER` nesses projetos) e `ipm-permission-observer` (`PROJECT_OWNER_VIEWER` e `ORG_OWNER_VIEWER`), que seguem sem processo. Sem o papel de organização o Zitadel devolve a lista de roles de `roles-operator` vazia e toda `*.admin` termina `Failed`. Em `stg` e `prd`, criar o Controller com esses papéis e completar os Grants de `roles-ipm` (`register` e `operator`) e as autorizações do operador com as roles `ipm.group.*` e `ipm.group.admin`; a suíte `identity/conformance` confere tudo.
- **Tipo de token das contas de serviço dos componentes** (decisão 0054, 2026-10-18): as seis (`*-executor` e `*-observer`) usam token **opaco (Bearer)**, o padrão do Zitadel para usuário de máquina (a API v2 omite o valor). Com JWT, o Zitadel registra um `WARN` por chamada. Ao criar uma conta de serviço, deixe o tipo em Bearer; a suíte de conformidade verifica. O `platform-bootstrap` segue JWT.
- **IP real no gateway:** `gateway/.env` aceita `SMARKEE_GATEWAY_TRUSTED_PROXIES` (um IP ou um CIDR, o do balanceador em stg/prd). Em dev, deixe vazio: o NAT do Docker esconde o IP real e confiar nele permitiria forjar `X-Forwarded-For`.
- **Nomes:** o projeto das roles do `core` se chama `roles-core` (decisão 0032; era `roles`, o ID não mudou) e a organização `register` guarda os usuários (decisões 0026 e 0027).
- **Autorizações dos projetos de roles na `core`:** só de operadores (decisão 0031): a role `*.admin` do tipo (escopo: qualquer instância) mais as roles de ação que ele exerce. O operador padrão tem todas. Usuários cadastrados são autorizados no contexto da `register`.
- **Project Grants → `register`:** um por projeto, com só as roles de ação (sem `*.admin`): `roles-core` (2 roles), `roles-ipm` (31: 5 de `ipm.organization`, 6 de `ipm.user`, 6 de `ipm.group`, 6 de `ipm.role`, 6 de `ipm.serviceaccount`, `ipm.permission.get|list`; o root recebe as de `ipm.user` pelo catálogo do SUM) e `roles-sum` (3). O Zitadel aplica o Grant como teto (API v2, decisão 0029).
- **Papel `ORG_USER_CREATOR`** (decisão 0032): papel de organização customizado (permissões do `ORG_USER_MANAGER` sem `user.grant.*`), carregado do arquivo `identity/role-permissions.yaml` pelo `identity` (`--config`). O arquivo é uma cópia integral do `RolePermissionMappings` do Zitadel v4.20.0 mais esse papel: a cada atualização do Zitadel, compare-o com o `defaults.yaml` da nova versão.
- **Variáveis da feature Account:** `CORE_ACCOUNT_IDENTITY_REGISTER_ORGANIZATION_ID` (organização `register`) e `CORE_ACCOUNT_IDENTITY_PROJECT_IDS` (JSON módulo → ID do projeto de roles que o Executor concede: `core` e `sum`). O Receiver usa a audience do próprio projeto.
- **Operadores:** autorização externa, criada na organização `core` para o usuário da organização `smarkee`, com `*.admin` e as roles de ação (`core.account.get|delete`, `ipm.organization.*`). Operador somente leitura: `*.admin` mais `get`/`list`, sem `delete`.

**Conferência da telemetria:** `tests/telemetry` faz um cadastro pelo gateway e confere, nos arquivos gravados, a correlação do `trace_id` entre o gateway e os componentes e a ausência de dados sensíveis (decisão 0059). `uv run pytest -q` na pasta; os usuários `conf.telemetry-*` são removidos pelo `smarkee-dev-cleanup`.

### Organization pronta para usuários (`ipm.user`, decisão 0081)

Não é mais atividade do operador. O loop da `ipm/organization` prepara cada organização de cliente: o Project Grant de `roles-ipm` com o catálogo `grantableRole` do contrato (`schemas/ipm/definitions.v1.schema.json`) e os papéis das contas do User (`ORG_USER_CREATOR` na organização e `PROJECT_GRANT_OWNER` no Grant para `ipm-user-executor`; `ORG_OWNER_VIEWER` na organização para `ipm-user-observer`), e as mesmas permissões às contas do ServiceAccount (`ipm-serviceaccount-executor` e `ipm-serviceaccount-observer`; decisão 0094). O Executor da Organization usa o `IAM_ORG_MANAGER` que já tem (decisão 0060). O `.env` da Organization precisa do projeto e das duas contas (`IPM_ORGANIZATION_IDENTITY_PROJECT_ID`, `IPM_ORGANIZATION_USER_EXECUTOR_ACCOUNT_ID` e `IPM_ORGANIZATION_USER_OBSERVER_ACCOUNT_ID`, `IPM_ORGANIZATION_SERVICEACCOUNT_EXECUTOR_ACCOUNT_ID`, `IPM_ORGANIZATION_SERVICEACCOUNT_OBSERVER_ACCOUNT_ID` e `IPM_ORGANIZATION_SERVICEACCOUNT_CONTROLLER_ACCOUNT_ID` e `IPM_ORGANIZATION_USER_CONTROLLER_ACCOUNT_ID`), conferidos pela suíte de conformidade. Ao recriar a instância do Zitadel, atualize esses IDs e reinicie o Manager: o rollout prepara as Organizations que existirem. O root recebe as roles `ipm.user.*` pelo catálogo do SUM (`SUM_SERVICE_MANAGER_CATALOG_ROLES`) ao habilitar o `ipm`; quem habilitou antes precisa desabilitar e habilitar de novo.

**Conferência da estrutura:** `identity/conformance` é uma suíte somente leitura que confere tudo acima (organizações, projetos de roles, o projeto `clients`, roles e `group`, aplicação `cli`, Project Grants, contas de serviço e papéis, o isolamento do Executor da Account, autorizações dos operadores e cadastro público desligado). Rode-a depois de criar ou recriar a estrutura; uso em `identity/conformance/README.md`. A criação continua manual (console ou API de gestão com a conta de bootstrap): a suíte não cria nada.

Para reproduzir pelo console (**Projetos**, **Autorizações**, **Configurações → Login**; os nomes das opções podem diferir um pouco na versão em uso): crie a organização `core`; nela, os projetos `roles-core`, `roles-ipm` e `roles-sum` (*Afirmar roles na autenticação* e *Verificar roles na autenticação* ligados) com as roles acima, o projeto `clients` (*Afirmar roles na autenticação* ligado e *Verificar roles na autenticação* **desligado**, sem roles) com a aplicação `cli` (nativa, PKCE, tipo de token JWT, redirect e concessões acima); desligue o registro na política de login; e delegue cada projeto à `register` por Project Grant só com as roles de ação; dê ao Executor da Account os papéis `ORG_USER_CREATOR` (na `register`) e `PROJECT_GRANT_OWNER` (nos Grants de `roles-core` e `roles-sum`); e conceda `*.admin` mais as roles de ação aos operadores.

Depois, no host, grave as sobrescritas do dev uma vez (`~/.config/sk/config.toml`, criado pelo primeiro `sk config set`; em produção a CLI não precisa de arquivo, decisão 0036) e faça o login:

```bash
cd clients/cli
uv run sk config set auth.issuer http://ipm-dev.smarkee.com.br:8080
uv run sk config set auth.clientId <client-id-da-aplicação-cli>
uv run sk config set api.url http://api-dev.smarkee.com.br:8080
uv run sk config set auth.allowInsecureHttp true   # dev não tem TLS
uv run sk config set api.allowInsecureHttp true
uv run sk config set core.projectId <ID-do-projeto-roles-core>
uv run sk config set sum.projectId <ID-do-projeto-roles-sum>
uv run sk config set ipm.projectId <ID-do-projeto-roles-ipm>
uv run sk auth login
```

- O login não verifica role (decisão 0034): quem não tem role em nenhum projeto entra, mas o token não vale em nenhum Receiver. A autorização está nos Receivers, que exigem a audience do próprio projeto e a role de ação.
- Use o issuer pelo gateway (`http://ipm-dev.smarkee.com.br:8080`), e não o endereço direto do `identity`: o `iss` dos tokens precisa ser esse endereço.
- O projeto, a aplicação e o client ID ficam gravados no banco do Zitadel. `docker compose down -v` os apaga, e o client ID muda ao recriá-los.
- Resta um projeto `smarkee` antigo na organização `smarkee` (5 roles, aplicação `cli` sem JWT; verificado em 2026-10-11). Ele sai depois de o login pelo projeto novo ser validado.
- O login completo foi exercitado pelo teste de jornada (`tests/e2e`), com um navegador falso que preenche as páginas de login, contra a aplicação `cli` do projeto `clients`.

### Conta de bootstrap da plataforma (`platform-bootstrap@smarkee.internal`)

`platform-bootstrap@smarkee.internal` é o usuário de máquina administrativo da instância do Zitadel (`IAM_OWNER`). Ele é usado **somente pela infraestrutura**, para configurar a plataforma no Zitadel: o projeto `roles`, as roles, a aplicação `cli` e um usuário de máquina por Executor, com papel mínimo (por exemplo, `ipm-organization-executor`). **Nenhum serviço de runtime usa essa conta** (decisão 0011): cada Executor tem a sua identidade (`docs/loop/RESOURCE-CONTROL-SECURITY.md`). A chave fica em `/zitadel/bootstrap/service-account-platform-bootstrap.json`, no volume `identity-bootstrap`.

- **Instância nova** (depois de `docker compose down -v`): o próprio Zitadel cria a conta e grava a chave, pelas variáveis `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*` e `ZITADEL_FIRSTINSTANCE_MACHINEKEYPATH` de `identity/compose.yaml`.
- **Instância existente**: as variáveis não se aplicam. Crie pelo console, uma vez:
  1. na organização `smarkee`, **Usuários → Usuários de serviço → Novo**: nome de usuário `platform-bootstrap`, tipo de token de acesso **JWT**;
  2. no usuário, **Chaves → Nova**, tipo **JSON**, com expiração; baixe o arquivo (ele só é exibido uma vez);
  3. em **Configurações padrão → Gerentes** (*Managers* da instância), adicione `platform-bootstrap@smarkee.internal` com o papel `IAM_OWNER`;
  4. copie a chave para o volume e apague a cópia local:

     ```bash
     docker cp <arquivo-baixado>.json identity.smarkee.internal:/zitadel/bootstrap/service-account-platform-bootstrap.json
     rm <arquivo-baixado>.json
     ```

- A chave é segredo: nunca a versione nem a copie para fora do volume. O padrão `service-account*.json` está no `.gitignore` como proteção adicional.
- O mecanismo definitivo que usa essa conta para aplicar a configuração do Zitadel em stg e prd (projeto, roles, aplicação e contas dos Executors) ainda será decidido. Em dev, foi aplicada pela API do Zitadel (seção anterior).
- A criação automática pela primeira instância ainda não foi verificada (exige recriar a instância). A criação manual segue os nomes do console da versão em uso, que podem diferir um pouco.

## Validade do access token (15 minutos)

A decisão 0033 encurta o access token da instância de 12 horas para **15 minutos**: uma revogação de role (por exemplo, ao desabilitar um serviço) chega ao token em até esse prazo, e a CLI renova a sessão pelo refresh token, sem pedir login. O ID token (12 h) e o refresh token (30 dias sem uso, 90 no total) não mudam.

- **Instância nova:** `ZITADEL_DEFAULTINSTANCE_OIDCSETTINGS_ACCESSTOKENLIFETIME: 15m` no `identity/compose.yaml` (aplicada só na criação da instância).
- **Instância existente (aplicado no dev em 2026-10-16):** Admin API **v1**, `PUT /admin/v1/settings/oidc`, com a conta de bootstrap. O corpo leva os quatro campos (`accessTokenLifetime`, `idTokenLifetime`, `refreshTokenIdleExpiration`, `refreshTokenExpiration`): leia com `GET` e reenvie os atuais, mudando só `accessTokenLifetime` para `"900s"`. A v1 é uma exceção registrada na decisão 0033: não existe API v2 para as configurações de OIDC.
- **Conferência:** `identity/conformance` lê a configuração e exige `900s`.
- **Contas de serviço:** os Executors e Observers pedem token por JWT bearer e o renovam sozinhos pelo `expires_in` da resposta; nada muda para eles.

## Rotação das chaves das contas de serviço

Cada conta de serviço tem uma chave JSON no volume `identity-bootstrap`, com validade. A rotação é manual e segue esta ordem, para o componente nunca ficar sem chave válida:

1. Gere um par RSA local (`openssl genrsa -out <arquivo>.pem 2048`) e envie a parte pública em PKIX PEM, codificada em base64, à API v2 (`POST /v2/users/<userId>/keys`, com `publicKey` e `expirationDate`). A resposta traz o `keyId`.
2. Grave no volume o JSON com `type`, `keyId`, `key` (a parte privada em PEM) e `userId`, substituindo o arquivo da conta. Dono `10001` e modo `0400`, como as chaves atuais. Passe o conteúdo pelo `stdin` de um contêiner `alpine` que escreve no volume, e apague o `.pem` local.
3. Reinicie só o componente da conta (`docker compose restart`) e confira `/health/ready` e uma ação de teste.
4. Remova a chave antiga pela API v2 (`POST /zitadel.user.v2.UserService/RemoveKey`, com `userId` e `keyId`).
5. Rode a suíte de conformidade (`infrastructure/dev/identity/conformance`).

Faça a rotação antes do aviso da suíte (90 dias antes do vencimento). A validade atual de cada conta está em `ListKeys` (`zitadel.user.v2.UserService`).

## Bootstrap

O estado inicial é configurado, em primeiro lugar, **por variáveis de ambiente ou pela forma mais simples que a ferramenta oferecer**. Arquivo de bootstrap é o último recurso, usado só quando não há alternativa; nesse caso, o serviço guarda o seu **estado inicial declarado** em `bootstrap/`: arquivos direto na raiz da pasta, cada um com o nome do que configura, em formato nativo da ferramenta e sem scripts. Por isso o Zitadel não tem pasta (primeira instância por `ZITADEL_FIRSTINSTANCE_*` e `ZITADEL_DEFAULTINSTANCE_*` em `identity/compose.yaml`), e database, messaging e gateway têm:

- database: as variáveis da imagem criam um único banco e usuário; são necessários três bancos com donos próprios, a localidade do `ssot` e as revogações de `PUBLIC`;
- messaging: o `nats-server` não declara Streams por configuração nem por variável, e serviços de runtime não podem criá-los (`docs/messaging/NATS.md`);
- gateway: o console web do APISIX exige a Admin API e o etcd (modo tradicional), que não aceitam um arquivo de rotas; o estado é aplicado pelo ADC a partir de `adc.yaml`. A configuração do servidor (`nats.conf`, `postgresql.conf`, `pg_hba.conf`, `pg_ident.conf`, `config.yaml` do gateway) fica fora de `bootstrap/`. Decisão em `.decisions/0005-bootstrap-declarativo-da-infraestrutura.md`.

| Serviço | Fonte | Quem aplica | Quando | Efeito de alterar um arquivo depois |
|---|---|---|---|---|
| database | `bootstrap/ssot.sql`, `identity.sql`, `core.sql` e `ipm.sql` (papéis de serviço dos módulos `core` e `ipm`: um por componente de cada tipo, inclusive o Publisher da Account e o da Organization) | A própria imagem (`/docker-entrypoint-initdb.d`) | Só na primeira inicialização do volume | Nenhum, até recriar o volume ou aplicar manualmente (pontos de atenção) |
| identity | Sem pasta: variáveis `ZITADEL_FIRSTINSTANCE_*` e `ZITADEL_DEFAULTINSTANCE_*` (nome da instância, marca d'água e textos de e-mail) em `identity/compose.yaml` | `identity-init` (`zitadel init zitadel`: schemas internos) → `identity` (`start-from-setup`) | Só na primeira inicialização da instância | Nenhum, até recriar a instância (`docker compose down -v`) |
| gateway | `bootstrap/adc.yaml` (formato do ADC: serviços, rotas e plugins) | `gateway-etcd` → `gateway` → `gateway-sync` (`adc sync`) | A cada `up`, depois que o `gateway` fica saudável | Reaplica na hora, sem reiniciar; remove do gateway o que saiu do arquivo (pontos de atenção) |
| messaging | `bootstrap/<stream>.json` (Stream do JetStream). Os consumers duráveis de cada tipo são das features (`consumers/` e `<módulo>-<tipo>-consumer` no `compose.yaml` delas) | Um serviço `messaging-bootstrap-<nome>` por arquivo | A cada `up`, depois que o messaging fica saudável | Falha de forma explícita até a alteração deliberada (abaixo) |
| features (fora deste diretório) | `features/core/account/migrations/*.sql` (schema `core`) e `features/ipm/organization/migrations/*.sql` (schema `ipm`): tabelas, views e privilégios no SSOT. O código é do Manager de cada tipo (decisão 0015) | `core-account-migrate` e `ipm-organization-migrate`, no `compose.yaml` da feature (`psql` como o dono `smarkee`, arquivos em ordem) | A cada `up`, depois que o banco fica saudável | Aplicado no próximo `up`; as migrações são idempotentes e seguem expandir → migrar → contrair (`docs/data/POSTGRESQL.md` §15) |

Os contêineres de inicialização equivalem a *initContainers*: cada um executa um único comando da CLI oficial e termina; o serviço seguinte declara `depends_on` com `service_completed_successfully`.

NATS:

- Os seis Streams operacionais de `docs/messaging/NATS.md` (os tipos `ipm/organization`, `ipm/serviceaccount` e `ipm/user` só usam `REQUESTED`, `DESIRED` e `UPDATED` desde a decisão 0096) são `REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT` e `UPDATED`. O `nats-server` não declara Streams no `nats.conf`; por isso, a criação é pela CLI oficial (imagem mínima `smarkee-nats-client:dev`, em `infrastructure/tools/nats-client`).
- **Todo arquivo novo em `messaging/bootstrap/` exige o seu serviço `messaging-bootstrap-<stream>`** em `messaging/compose.yaml` (âncora `x-messaging-bootstrap`); sem ele, o arquivo é ignorado.
- O Stream `ACTION` é **particionado** por `resourceId` (`subject_transform` em `bootstrap/action.json`, 4 partições, decisão 0018): o Subject armazenado ganha o token da partição, e cada Executor tem um consumer por partição. Mudar o número de partições exige recriar o Stream e os consumers.
- Stream inexistente é criado; existente com a mesma configuração não muda. Com configuração diferente, o contêiner falha (`stream name already in use with a different configuration`). Para aplicar a alteração de forma deliberada:

  ```bash
  SMARKEE_MESSAGING_PASSWORD=$(grep '^SMARKEE_MESSAGING_PASSWORD=' messaging/.env | cut -d= -f2)
  docker run --rm --network internal -v "$PWD/messaging/bootstrap:/bootstrap:ro" smarkee-nats-client:dev \
    nats -s nats://messaging.smarkee.internal:4222 --user smarkee --password "$SMARKEE_MESSAGING_PASSWORD" stream edit OBSERVED --config /bootstrap/observed.json --force
  ```

  Campos imutáveis (`retention`, `storage`) não podem ser editados: o Stream precisa ser removido e recriado, com perda das mensagens.
- Os limites são valores de desenvolvimento. `DESIRED` não possui limite de tamanho nem de quantidade total: com descarte do mais antigo, um limite apagaria o estado de outros recursos.
- Os consumers duráveis de cada tipo são das features: os manifestos ficam em `consumers/`, e o serviço `<módulo>-<tipo>-consumer` do `compose.yaml` da feature os cria (por exemplo, as features migradas para API síncrona (`core/account`, `sum/service` e as do `ipm`) não têm mais consumers de trabalho: o Controller cria os próprios, decisões 0096 e 0098).
- Valores aplicados em dev (`bootstrap/*.json`): todos os Streams em arquivo, 1 réplica, janela de deduplicação de 2 min e `max_msg_size` de 1 MiB. `REQUESTED` e `ACTION`: `workqueue`, `discard new`, 100.000 mensagens e 1 GiB. `DESIRED`: `limits`, 1 mensagem por Subject, `allow_direct`, sem limite de idade. `OBSERVED`: 1 mensagem por Subject, idade máxima de 24 h. `RESULT`: `allow_direct`, 1 GiB, idade máxima de 3 dias. `UPDATED`: 1 GiB, idade máxima de 24 h.
- **Neste diretório, não use `docker compose up -d --wait` sem nomear serviços.** O `--wait` só aceita um contêiner de inicialização terminado quando outro serviço depende dele: ao ver um `messaging-bootstrap-*` terminar, ele **interrompe a espera** com `container messaging-bootstrap-<stream> exited (0)`, antes de os demais ficarem saudáveis. Use os dois comandos de "Subir e derrubar": o primeiro sobe tudo; o segundo espera somente os serviços de longa duração. Confira a inicialização com `docker compose ps -a` (todos os contêineres de inicialização com `Exited (0)`).

Zitadel: o volume `identity-bootstrap` (`/zitadel/bootstrap` no contêiner) guarda o PAT gerado do cliente de login, que o `identity-login` usa para se autenticar na API do Zitadel, e a chave da conta de bootstrap da plataforma (`service-account-platform-bootstrap.json`). É estado de runtime, e não configuração.

SSOT: num volume do banco já existente, os papéis de `database/bootstrap/core.sql` e `ipm.sql` não são criados sozinhos; aplique os arquivos de bootstrap manualmente (pontos de atenção) antes do primeiro `*-migrate`. Sem os papéis, a migração falha nos `GRANT`.

## Exemplos

PostgreSQL (o banco `ssot` é o SSOT, conforme `docs/data/POSTGRESQL.md`; as tabelas dos tipos `core.account` e `ipm.organization` são criadas pelas migrações das features):

```bash
# Com psql instalado no host
psql "postgresql://ssot:ssot@localhost:5432/ssot"
# Sem psql no host: dentro do container (socket local, sem senha)
docker exec -it database.smarkee.internal psql -U ssot -d ssot
docker exec -it database.smarkee.internal psql -U postgres            # administrador
```

NATS (sem a CLI `nats` no host, use a imagem mínima `smarkee-nats-client:dev` com a rede do host):

```bash
SMARKEE_MESSAGING_PASSWORD=$(grep '^SMARKEE_MESSAGING_PASSWORD=' messaging/.env | cut -d= -f2)
docker run --rm --network host smarkee-nats-client:dev nats -s nats://localhost:4222 --user smarkee --password "$SMARKEE_MESSAGING_PASSWORD" account info
docker run --rm --network host smarkee-nats-client:dev nats -s nats://localhost:4222 --user smarkee --password "$SMARKEE_MESSAGING_PASSWORD" stream ls
```

Zitadel e gateway:

```bash
curl -s http://ipm-dev.smarkee.com.br:8080/.well-known/openid-configuration   # discovery OIDC
KEY=$(grep ^SMARKEE_GATEWAY_ADMIN_KEY= gateway/.env | cut -d= -f2)
curl -s -H "X-API-KEY: $KEY" http://localhost:9180/apisix/admin/services      # serviços do gateway
curl -s -H "X-API-KEY: $KEY" http://localhost:9180/apisix/admin/routes        # rotas do gateway
```

Zitadel direto, sem o gateway (de um container na rede `internal`):

```bash
docker run --rm --network internal curlimages/curl -s -H 'Host: ipm-dev.smarkee.com.br:8080' http://identity.smarkee.internal:8080/.well-known/openid-configuration
```

## Pontos de atenção

- O gateway guarda a configuração no etcd (volume `gateway-etcd-data`). O `gateway-sync` (ADC) é uma reconciliação: a cada `up` ele cria, atualiza e **remove** serviços e as rotas de dentro deles para igualar `gateway/bootstrap/adc.yaml`. Rotas **soltas** (sem serviço), que é como o console web as cria, não são tocadas pelo ADC e ficam só no etcd; para uma rota durável, declare-a no `adc.yaml`. Depois de alterar o arquivo, reaplique com `docker compose up -d gateway-sync` (ou `docker compose run --rm gateway-sync`); não é preciso reiniciar o gateway. O `gateway-sync` tenta até 5 vezes: depois de recriar o etcd (por exemplo, ao trocar a versão da imagem), o APISIX demora alguns segundos para voltar a enxergá-lo, e as primeiras tentativas falham com `503`.
- O ADC marca o backend do APISIX como experimental e a documentação dele lista as versões do APISIX testadas até a 3.17; a 3.19 funciona em dev (decisão 0049), mas confira o `gateway-sync` ao atualizar o APISIX.
- A inicialização do Zitadel (`identity-init`) aguarda o PostgreSQL aceitar conexões (`depends_on` com `service_healthy`), declarado no próprio `compose.yaml` de cada recurso, que inclui o `database/compose.yaml`.
- O gateway envia o `X-Forwarded-Host` sem a porta. O login do Zitadel (Next.js) usa esse cabeçalho nos redirecionamentos e o compara com o `Origin` do navegador (proteção das Server Actions). Com o proxy em porta diferente da 80, os redirecionamentos podem perder a porta e o envio do usuário falhar com "erro interno" (`x-forwarded-host ... does not match origin` no log do `identity-login`); isso foi observado quando o proxy estava em outra porta. O login do administrador na porta 8080 foi confirmado no navegador. `SMARKEE_GATEWAY_PROXY_HTTP_PORT` e `SMARKEE_IDENTITY_EXTERNAL_PORT` devem permanecer iguais; a instância do Zitadel guarda a porta da primeira inicialização.
- O nome de login do Zitadel é `usuário@domínio-da-organização`. Nesta instância o sufixo da organização está ligado (*Configurações da instância → Domain settings → Add Organization Domain as suffix to loginnames*) e a organização foi renomeada para `smarkee`; por isso `admin` sozinho não é aceito. O administrador entra por `admin@smarkee.internal` (o e-mail) ou `admin@smarkee.ipm-dev.smarkee.com.br`. Essas alterações (sufixo ligado e nome da organização) ficam gravadas no banco do Zitadel: `docker compose down -v` as desfaz, e a instância nova volta aos valores de `identity/.env` (`ZITADEL_FIRSTINSTANCE_*`), com o sufixo desligado. A opção *Organization Domain verification required* deve ficar desligada em dev, pois exige desafio por DNS ou HTTP.
- O Zitadel monta o issuer e as URLs públicas a partir do cabeçalho `x-zitadel-public-host`, preenchido pelo gateway com o `Host` original (plugin `proxy-rewrite` da rota `identity`).
- Os arquivos de `database/bootstrap/` só rodam na primeira inicialização do volume. Em um volume existente, aplique-os manualmente:

  ```bash
  docker exec database.smarkee.internal sh -c 'for f in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f $f; done'
  ```

- A senha trivial do banco `identity` deve ser trocada antes de qualquer ambiente `stg` ou `prd`.
- O NATS usa um único usuário em dev. A identidade e as permissões por serviço de `docs/messaging/NATS.md` e `docs/loop/RESOURCE-CONTROL-SECURITY.md` não são exercitadas aqui; erros de permissão só aparecem em ambientes que as aplicam.
- Na subida a frio, o gateway pode responder 502/503 para um serviço que ainda não existia por alguns segundos, até resolver o nome. Normaliza sozinho.
- Depois de recriar o contêiner de um Receiver (por exemplo, `docker compose up -d --build` de uma feature), o APISIX volta a resolver o nome sozinho: medido na PoC, a rota se recuperou em cerca de 3 s (com `502` nesse intervalo). Não é preciso reiniciar o gateway.
- Desenvolvimento apenas: o Zitadel roda como root, não há TLS e não há arquivamento de WAL (o procedimento de recuperação do SSOT não é testável aqui).
- O PostgreSQL registra esperas por bloqueio (`log_lock_waits`) e comandos acima de 500 ms, sem os valores dos parâmetros: `docker logs database.smarkee.internal`.
- Traces (decisão 0050): o plugin `opentelemetry` está ligado em todas as rotas e exporta para o `telemetry-router`, que o roteia ao telemeter dono (a rota de `core/account`, ao `core-account-telemeter`; as demais, ao `platform-telemeter`), e os telemeters gravam em arquivos até haver um backend: `platform-telemeter/logs/app` e `logs/infra`, `metrics/app` e `metrics/infra`, e `traces/` (decisão 0053; o ativo é `<sinal>.jsonl`, uma linha OTLP JSON por lote; ao chegar a 10 MB é renomeado `<sinal>-<data>-size.jsonl`, e ficam 3 rotacionados, por até 1 dia; o conteúdo é ignorado pelo git). **App** é o que traz `smarkee.component.role` (logs dos componentes) e o que não é `container.*`/`system.*`/`process.*`/`k8s.*` (métricas); o resto é **infra**. O limite está em `rotation` de cada exporter `file` em `platform-telemeter/config.yaml` (e `features/core/account/telemeter/config.yaml`). No Linux, as pastas precisam ser graváveis pelo usuário 10001 (`chmod -R o+rwx`). Um registro único acima de 10 MB é rejeitado (erro no log do coletor; quem envia ainda recebe 200). Com o coletor parado o gateway registra um `[error] request failed: connection refused` por lote de spans, sem afetar as requisições. O processador `telemetry-router/gateway-semconv.yaml` ajusta os spans à semconv e redige a query; um coletor que o dispense recebe os spans fora da semconv e com a query sem redação (`http.target`). O coletor não publica portas no host: a stack de observabilidade do desenvolvedor, quando está no ar, já usa 4317 e 4318. A imagem não tem shell, por isso não há healthcheck do Compose.
- Telemetria dos contêineres (decisão 0051): o `telemetry-agent` envia ao `telemetry-router` as métricas de CPU, memória e rede dos contêineres `*.smarkee.internal` e os logs JSON dos componentes das features (os 18 que usam o driver `json-file` e o formato da decisão 0045). Os contêineres da plataforma (`messaging`, `database`, `identity`, `gateway`, `mail`) usam o driver `local` do Docker Desktop, que o `file_log` não lê: só as métricas deles entram. O agente descarta o que não é um componente da plataforma. Ele monta o socket do Docker e `/var/lib/docker/containers` e roda como root (sem capabilities), o que vale só em dev. Para ver o que chega: `tail -f infrastructure/dev/platform-telemeter/logs/app/logs.jsonl` (ou, para `core/account`, `features/core/account/telemeter/logs/logs.jsonl`). Os healthchecks são descartados no agente; os logs de infra só guardam `WARN` ou acima (política enxuta inicial) e sem as linhas de acesso do nginx. Declarar `plugins:` no `gateway/config.yaml` substitui a lista padrão do APISIX; ao atualizar a imagem, compare com a lista padrão da nova versão.
- Autenticação na borda (decisão 0052): o plugin `openid-connect` valida o token nas rotas de API (`/v1/core/accounts/*` e demais métodos de `/v1/core/accounts`, `/v1/ipm/organizations*` e `/v1/sum/services*`): assinatura RS256 pelo JWKS do Zitadel, emissor, audiência do módulo (`SMARKEE_GATEWAY_AUTH_AUDIENCE_*`), `exp`, `sub`, `iss` e `aud`. Continuam públicas as rotas do Zitadel e o cadastro (`POST /v1/core/accounts`). O gateway só **autentica**: as roles e o dono continuam nos Receivers, que repetem a validação do token. O `401` do gateway segue o contrato `ApiError` (`WWW-Authenticate: Bearer realm="smarkee"`, sem descrição do erro); o motivo fica no log do gateway (`OIDC introspection failed: ...`), e o `401` do próprio Receiver passa intacto.
- O gateway busca o discovery e o JWKS no endereço do issuer (`http://ipm-dev.smarkee.com.br:8080`). Dentro da rede esse nome é um alias do próprio `gateway`, que atende a porta `8080` (além da `8000`) e encaminha ao Zitadel; mantenha o alias, a porta e `SMARKEE_IDENTITY_EXTERNAL_DOMAIN`/`SMARKEE_IDENTITY_EXTERNAL_PORT` iguais. Todo contêiner da rede `internal` passa a resolver `ipm-dev.smarkee.com.br` para o gateway.
- Zitadel parado: com o gateway reiniciado a frio, as rotas autenticadas respondem `401` (falha fechada) até o discovery voltar; depois que o Zitadel volta, o gateway se recupera sozinho em cerca de 16 s (medido). O JWKS fica em cache por 1 h (`jwk_expires_in`): uma chave nova é reconhecida na hora (o `kid` desconhecido força a busca), mas uma chave retirada do JWKS ainda deve valer por até 1 h (não medido).
- A validação é local, sem consultar o Zitadel a cada pedido: um token de usuário desativado ou com sessão encerrada vale até o `exp` (15 minutos). O gateway não verifica `nbf` (os Receivers sim).
- Limites de recursos (decisão 0053): todo contêiner de longa duração tem `deploy.resources.limits` calibrados com o consumo medido em dev, ajustáveis por variável de ambiente (`<SERVIÇO>_CPUS` e `<SERVIÇO>_MEMORY`, por exemplo `SMARKEE_DATABASE_MEMORY`; nas features, `<MÓDULO>_<TIPO>_COMPONENT_CPUS` e `_MEMORY`). Padrões: componentes 0,5 CPU e 256 MiB; `database` e `identity` 1,0 CPU e 512 MiB; `identity-login` 0,5 CPU e 512 MiB; `gateway` 1,0 CPU e 384 MiB; `messaging` e `gateway-etcd` 0,5 CPU e 256 MiB; `mail` 0,25 CPU e 256 MiB; `telemetry-router` 0,5 CPU e 256 MiB; `platform-telemeter` e `telemetry-agent` 0,5 CPU e 384 MiB; `core-account-telemeter` 0,25 CPU e 192 MiB. Medido: pior uso de memória 36% do limite. O *throttling* de CPU que aparece nos componentes (6 períodos por 30 s) vem do healthcheck `python -c` a cada 10 s, não do trabalho do componente.
- Logs da plataforma (decisão 0053): `messaging`, `database`, `identity`, `identity-login`, `gateway`, `gateway-etcd`, `mail` e os dois coletores usam `json-file` com as labels `com.docker.compose.service` e `smarkee.layer=infra` (o agente só lê os que têm a segunda); um contêiner novo da plataforma precisa do mesmo bloco `logging` e da label para ter os logs coletados. Fora o que o agente descarta (healthchecks, `INFO` da infra), os `WARN` do Zitadel `decrypt access token` e `Usuário não pôde ser encontrado` são benignos e frequentes.
- A Admin API e o console web exigem a `SMARKEE_GATEWAY_ADMIN_KEY`, mas o etcd não tem autenticação e a Admin API aceita conexões de toda a rede `internal`; não exponha as portas `9180` e `2379` fora de `127.0.0.1` e da rede de dev.
- **Depois de recriar um Receiver** (o contêiner ganha outro IP), o gateway pode continuar enviando ao IP antigo até o cache de DNS dele expirar, e a requisição cai em outro contêiner (observado em 2026-10-19: `405` vindo de um serviço que só aceita `GET`). Reinicie o gateway (`docker compose restart gateway` nesta pasta) ou aguarde alguns minutos.
- O limite de taxa do cadastro usa o IP do cliente dado pelo plugin `real-ip` (decisão 0054). Em dev, `SMARKEE_GATEWAY_TRUSTED_PROXIES` fica vazio e vale o IP do par TCP (o NAT do Docker esconde o real); atrás de um balanceador (stg e prd) defina nela o IP ou o CIDR do balanceador. O `429` do plugin `limit-count` não traz `Retry-After`; a rota `core-account-register` o acrescenta com `response-rewrite` (60 s, a janela inteira).
