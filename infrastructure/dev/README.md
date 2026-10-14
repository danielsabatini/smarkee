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
for s in database broker identity gateway; do cp -n $s/.env.example $s/.env; done
```

Preencha os valores obrigatórios (vazios no exemplo) antes de subir:

| Arquivo | Variável | Valor |
|---|---|---|
| `database/.env` | `POSTGRES_PASSWORD` | Senha do administrador `postgres`: `openssl rand -hex 16` |
| `broker/.env` | `NATS_PASSWORD` | Senha do usuário do NATS: `openssl rand -hex 16` |
| `identity/.env` | `ZITADEL_MASTERKEY` | Exatamente 32 caracteres: `openssl rand -hex 16`. Não altere depois da primeira subida |
| `identity/.env` | `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD` | Senha inicial do administrador do Zitadel, com maiúscula, minúscula, número e símbolo |
| `identity/.env` | `ZITADEL_SESSION_COOKIE_SECRET` | `openssl rand -hex 32` |
| `features/core/user/.env` | `CORE_USER_<PAPEL>_NATS_PASSWORD` (`RECEIVER`, `MANAGER`, `PUBLISHER`, `RECONCILER`, `OBSERVER`, `EXECUTOR`) | A mesma `NATS_PASSWORD` de `broker/.env` |
| `features/ipm/organization/.env` | `IPM_ORGANIZATION_<PAPEL>_NATS_PASSWORD` (`RECEIVER`, `MANAGER`, `RELAY`) | A mesma `NATS_PASSWORD` de `broker/.env` |
| `features/core/user/.env` e `features/ipm/organization/.env` | `CORE_USER_RECEIVER_AUTH_AUDIENCE`, `IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE` | ID do projeto `roles` no Zitadel (organização `core`) |

Os componentes das features (User e Organization) **não são subidos por este diretório**: cada feature tem o seu `compose.yaml` e o seu `.env` (`cp .env.example .env` em `features/core/user` e `features/ipm/organization`), e eles esperam a plataforma abaixo no ar. Suba a plataforma primeiro e depois cada feature (`docker compose up -d --build` na pasta dela). Se recriar o Receiver de uma feature, reinicie o `gateway`, que guarda em cache o endereço do contêiner.

Variáveis adicionais configuradas no `identity/.env`:
- `ZITADEL_FIRSTINSTANCE_INSTANCENAME`: Nome da instância exibido no console (padrão: `IPM`).
- `ZITADEL_FIRSTINSTANCE_ORG_NAME`: Nome da organização inicial (padrão: `smarkee.internal`).
- `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_USERNAME`: Nome do usuário administrador (padrão: `admin`).
- `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_EMAIL`: E-mail do administrador (padrão: `admin@smarkee.internal`).
- `ZITADEL_EXTERNALDOMAIN`: Domínio público de acesso (padrão: `ipm-dev.smarkee.com.br`).
- `ZITADEL_EXTERNALPORT`: Porta pública de acesso (padrão: `8080`, igual a `KONG_PROXY_HTTP_PORT`).

`gateway/.env` não possui valor obrigatório (`KONG_PROXY_HTTP_PORT=8080` por padrão).

## E-mail de desenvolvimento (Mailpit)

O serviço `mail` captura o SMTP do Zitadel (`mail.smarkee.internal:1025`, só na rede `internal`); nada sai da máquina. A interface web fica em http://localhost:8025 (somente no host) e mostra os e-mails de ativação e de redefinição de senha.

- **Instância nova:** o `identity/compose.yaml` já aponta o Zitadel para o Mailpit (`ZITADEL_DEFAULTINSTANCE_SMTPCONFIGURATION_*`, aplicado só na primeira inicialização).
- **Instância existente:** a configuração SMTP é da instância, e não de variável. Aplique pela Admin API ou pelo console (**Configurações → SMTP**): host `mail.smarkee.internal:1025`, sem TLS, remetente `ipm-dev@smarkee.internal` e nome `IPM-DEV`. Há um e-mail de teste no console.
- **Destinatário:** o Mailpit só captura; **ninguém recebe** os e-mails, e por isso testes com `example.com` são seguros. Para enviar de verdade em dev, troque a configuração SMTP ativa para um provedor real (por exemplo, o Brevo) no console, sem versionar a chave, e volte ao Mailpit depois: só uma configuração fica ativa por instância. Em stg e prd o SMTP é sempre o provedor real.

## Subir e derrubar

```bash
docker compose up -d                                                 # sobe tudo, inclusive os contêineres de inicialização
docker compose up -d --wait broker gateway identity identity-login mail   # espera os serviços de longa duração ficarem saudáveis
docker compose ps                                                    # estado e saúde
docker compose down              # derruba, preservando os volumes
docker compose down -v           # derruba e APAGA os dados
```

Os contêineres de inicialização permanecem parados (`Exited (0)`) depois de executar, preservando o código de saída e os logs para diagnóstico (`docker compose ps -a`, `docker compose logs <serviço>`). O Compose não os remove automaticamente: não há equivalente ao `docker run --rm`, e o `depends_on: service_completed_successfully` precisa do contêiner encerrado para ler o código de saída. A próxima subida os recria.

Cada serviço também sobe isoladamente em seu próprio diretório (`cd database && docker compose up -d`). Use **um modo por vez**: os nomes dos containers são fixos e conflitam entre os dois modos. Cada recurso tem um único `compose.yaml`. O `identity` e o `gateway` incluem o `database/compose.yaml`: isolados, sobem o PostgreSQL junto e aguardam que ele aceite conexões.

## Como acessar

Com a stack de pé (`docker compose ps`) e o `/etc/hosts` configurado:

| O que | Endereço | Credencial |
|---|---|---|
| Console do Zitadel | http://ipm-dev.smarkee.com.br:8080/ui/console/ | Usuário `admin@smarkee.internal` (ou `admin@smarkee.ipm-dev.smarkee.com.br`) e a senha `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD` de `identity/.env` (troca obrigatória no primeiro acesso) |
| Cadastro de nova organização (Zitadel) | http://ipm-dev.smarkee.com.br:8080/ui/login/register/org | **Desligado** (decisão 0013): o cadastro público foi desativado na política de login; usuários e organizações nascem pelo Receiver |
| API da plataforma | http://api-dev.smarkee.com.br:8080/v1/ | Token do `sk auth login` (`Authorization: Bearer`); o cadastro (`POST /v1/users`) é anônimo, com limite de taxa |
| Kong Manager | http://localhost:8002 | Nenhuma |
| Kong Admin API | http://localhost:8001 | Nenhuma |
| PostgreSQL | `psql "postgresql://smarkee:smarkee@localhost:5432/smarkee"` | Ver "Credenciais" |
| NATS | `nats://smarkee:<NATS_PASSWORD>@localhost:4222` · monitoramento em http://localhost:8222 | `NATS_PASSWORD` de `broker/.env` |

- Use o nome `ipm-dev.smarkee.com.br` **com a porta `:8080`** no navegador. O endereço `localhost:8080` não é roteado (o gateway roteia por host) e responde 404.
- De um contêiner na rede `internal`, use os nomes `*.smarkee.internal` da coluna **Rede `internal`** do mapa abaixo; `localhost` ali aponta para o próprio contêiner.
- Todas as portas são publicadas apenas em `127.0.0.1`.
- **Nome de login no Zitadel:** informe o nome completo, `usuário@domínio-da-organização`, ou o e-mail do usuário. Digitar só `admin` retorna "usuário não encontrado". Para o administrador: `admin@smarkee.internal` ou `admin@smarkee.ipm-dev.smarkee.com.br`. O domínio de uma organização é `<nome-da-organização>.ipm-dev.smarkee.com.br` (por exemplo, `core.ipm-dev.smarkee.com.br`, confirmado no token); o e-mail do usuário também funciona.
- O cadastro público do Zitadel (usuário e organização) está **desligado**: usuários e organizações nascem pela API da plataforma (decisões 0013 e 0014). A porta faz parte do endereço (`ZITADEL_EXTERNALPORT`); em outros ambientes o endereço será outro.

## Mapa de acesso

Do host, use a coluna **Host**. De um container na rede `internal` (por exemplo, um serviço do projeto rodando em Docker), use a coluna **Rede `internal`**: dentro de um container, `localhost` e `*.localhost` apontam para o próprio container.

| Sistema | Host | Rede `internal` | Observação |
|---|---|---|---|
| Zitadel (console) | http://ipm-dev.smarkee.com.br:8080/ui/console/ | — | Navegador, via gateway |
| Zitadel (login) | http://ipm-dev.smarkee.com.br:8080/ui/v2/login/ | — | Navegador, via gateway |
| Zitadel (OIDC e APIs) | http://ipm-dev.smarkee.com.br:8080 | http://gateway.smarkee.internal:8000 com o cabeçalho `Host: ipm-dev.smarkee.com.br:8080` | Ver a seção OIDC |
| Zitadel API (direto, sem gateway) | — (porta não publicada) | http://identity.smarkee.internal:8080 com o cabeçalho `Host: ipm-dev.smarkee.com.br:8080` | Chamadas entre serviços e diagnóstico; sem o cabeçalho responde 404 |
| Zitadel login (direto, sem gateway) | — (porta não publicada) | http://identity-login.smarkee.internal:3000/ui/v2/login/ | Somente diagnóstico (`/ui/v2/login/healthy`) |
| Kong (proxy HTTP) | http://ipm-dev.smarkee.com.br:8080 | http://gateway.smarkee.internal:8000 | Roteia por host (`gateway/bootstrap/routes.yml`); host desconhecido responde 404 |
| Receiver de User (`core`) | http://api-dev.smarkee.com.br:8080/v1/users (só `/v1/users`) | http://core-user-receiver.smarkee.internal:8000 | `/health/*` só na rede interna. O cadastro anônimo (`POST /v1/users`) tem limite de 10 por minuto por IP no gateway (rota `core-user-register`) e de 5 por 60 s por origem no Receiver |
| Receiver de Organization (`ipm`) | http://api-dev.smarkee.com.br:8080/v1/organizations (só `/v1/organizations`) | http://ipm-organization-receiver.smarkee.internal:8000 | `/healthz` só na rede interna (desenho anterior: a Organization ainda adota a estrutura do User) |
| Kong (proxy HTTPS) | https://localhost:8443 | https://gateway.smarkee.internal:8443 | Certificado autoassinado (`curl -k`); não use para o Zitadel (ver OIDC) · responde 404 sem um host roteado |
| Kong Admin API | http://localhost:8001 · https://localhost:8444 | http://gateway.smarkee.internal:8001 | Sem autenticação |
| Kong Manager | http://localhost:8002 · https://localhost:8445 | — | Navegador; sem autenticação |
| PostgreSQL | `localhost:5432` | `database.smarkee.internal:5432` | Senha obrigatória por TCP (SCRAM) |
| NATS (cliente) | `nats://localhost:4222` | `nats://broker.smarkee.internal:4222` | Usuário e senha obrigatórios |
| NATS (monitoramento) | http://localhost:8222 | http://broker.smarkee.internal:8222 | `/healthz`, `/varz`, `/jsz`; sem autenticação |

O gateway trata somente HTTP e HTTPS e roteia por host: o Zitadel atende `ipm-dev.smarkee.com.br`, e cada novo Receiver recebe um host próprio (por exemplo, `api.localhost`). No host, aponte `127.0.0.1 ipm-dev.smarkee.com.br` em `/etc/hosts`. O NATS e o PostgreSQL são acessados diretamente, sem o gateway.

O proxy HTTP do gateway é publicado na porta 8080 do host (no container, continua na 8000). A porta 80 não é usada porque costuma estar ocupada por outros serviços locais (por exemplo, ingress de clusters Kubernetes locais). O `ZITADEL_EXTERNALPORT` precisa ser igual à porta publicada do proxy (ver pontos de atenção).

Somente o gateway publica portas do Zitadel. O acesso direto ao `identity` e ao `identity-login` existe apenas na rede `internal`, e o Zitadel escolhe a instância pelo domínio, por isso o cabeçalho `Host` é obrigatório e **deve incluir a porta** (`Host: ipm-dev.smarkee.com.br:8080`): sem a porta, o issuer devolvido perde o `:8080` e não confere com o dos tokens emitidos pelo navegador. O navegador (console e login) deve sempre passar pelo gateway: os redirecionamentos e o issuer apontam para `http://ipm-dev.smarkee.com.br:8080`, e só o gateway reúne o Receiver e o login no mesmo domínio.

## Credenciais

Valores sensíveis ficam nos arquivos `.env` (fora do git). As senhas dos bancos de aplicação são triviais e fixas em `database/bootstrap/*.sql`.

| Sistema | Usuário | Senha | Onde está |
|---|---|---|---|
| Zitadel (administrador) | `admin@smarkee.internal` ou `admin@smarkee.ipm-dev.smarkee.com.br` | `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD` | `identity/.env` (troca obrigatória no primeiro acesso) |
| PostgreSQL (administrador) | `postgres` | `POSTGRES_PASSWORD` | `database/.env` |
| PostgreSQL, banco `smarkee` (SSOT, proprietário) | `smarkee` | `smarkee` | `database/bootstrap/smarkee.sql` |
| PostgreSQL, banco `identity` | `identity` | `identity` | `database/bootstrap/identity.sql` (o Zitadel usa só este usuário, sem credencial de administrador) |
| PostgreSQL, banco `gateway` | `gateway` | `gateway` | `database/bootstrap/gateway.sql` |
| PostgreSQL, banco `smarkee` (módulo `core`, User) | `core_user_manager_login`, `core_user_receiver_login`, `core_user_publisher_login`, `core_maintenance_login` | igual ao usuário | `database/bootstrap/core.sql` |
| PostgreSQL, banco `smarkee` (módulo `ipm`, Organization) | `ipm_organization_manager_login`, `ipm_organization_receiver_login`, `ipm_organization_relay_login`, `ipm_maintenance_login` | igual ao usuário | `database/bootstrap/ipm.sql` |
| NATS | `NATS_USER` (`smarkee`) | `NATS_PASSWORD` | `broker/.env` (um único usuário em dev, compartilhado pelos serviços) |
| Kong Manager / Admin API | — | — | Sem autenticação (Kong OSS) |

O usuário `smarkee` é o proprietário do SSOT, destinado a migrações (`docs/POSTGRESQL.md`). Cada serviço usa um papel de login próprio, membro de um papel de função sem login (`docs/POSTGRESQL.md` §14.2 e §14.3). Criar papéis exige `CREATEROLE`, que o `smarkee` não tem: os papéis são criados como administrador em `database/bootstrap/<módulo>.sql`, e os privilégios são concedidos pela migração do módulo.

## Strings de conexão

| Destino | Do host | Da rede `internal` |
|---|---|---|
| SSOT (proprietário) | `postgresql://smarkee:smarkee@localhost:5432/smarkee` | `postgresql://smarkee:smarkee@database.smarkee.internal:5432/smarkee` |
| NATS | `nats://smarkee:<NATS_PASSWORD>@localhost:4222` | `nats://smarkee:<NATS_PASSWORD>@broker.smarkee.internal:4222` |

Não há TLS em dev (`sslmode=disable` quando o cliente exigir o parâmetro).

## OIDC (Zitadel)

| Item | Valor |
|---|---|
| Issuer | `http://ipm-dev.smarkee.com.br:8080` |
| Discovery | `http://ipm-dev.smarkee.com.br:8080/.well-known/openid-configuration` |
| JWKS | `http://ipm-dev.smarkee.com.br:8080/oauth/v2/keys` |
| Autorização / token | `http://ipm-dev.smarkee.com.br:8080/oauth/v2/authorize` · `/oauth/v2/token` |

- Use sempre o endereço HTTP da porta 8080 (`http://ipm-dev.smarkee.com.br:8080`). O issuer é derivado do endereço de acesso: pelo HTTPS da porta 8443 ele seria `https://ipm-dev.smarkee.com.br:8443`, e tokens emitidos por um endereço não validam no outro.
- Um serviço em container obtém o discovery e o JWKS por `http://gateway.smarkee.internal:8000` ou, sem o gateway, por `http://identity.smarkee.internal:8080`, em ambos os casos com o cabeçalho `Host: ipm-dev.smarkee.com.br:8080`, e valida o `iss` contra `http://ipm-dev.smarkee.com.br:8080`.

### Configuração do Zitadel para a plataforma (`sk auth login`)

O `sk` autentica direto no Zitadel, pelo gateway, sem API própria de autenticação (Authorization Code com PKCE e retorno em `127.0.0.1`; uso em `components/cli/README.md`). Ele usa o projeto da plataforma e a sua aplicação nativa. Pelas decisões 0010, 0013 e 0014, o desenho é:

| Organização | Papel |
|---|---|
| `smarkee` | Só operadores e contas administrativas da instância (`admin`, `platform-bootstrap`, `login-client`). Não tem recursos da plataforma |
| `core` | Organização de sistema da plataforma: dona do projeto `roles`. Sem usuários cadastrados e sem papéis das contas de serviço |
| `register` | Usuários cadastrados (decisões 0026 e 0027). Recebe o projeto `roles` por Project Grant (só as roles de ação, sem as `*.admin`) |

Estado aplicado no dev em 2026-10-10 (pela API do Zitadel, com a conta de bootstrap; o script usado é temporário e não versionado):

- **Projeto `roles`, na organização `core`:** roles no token e **verificação de role na autenticação** ligadas.
- **Roles por ação:** `ipm.organization.create`, `ipm.organization.get`, `ipm.organization.list`, `ipm.organization.update`, `ipm.organization.delete`, `core.user.get`, `core.user.delete`, e, para operadores, `core.user.admin` e `ipm.organization.admin`. Padrão `<módulo>.<tipo>.<ação>` (decisão 0028); no Zitadel cada role tem o módulo como `group`.
- **Aplicação `cli`:** nativa, PKCE, redirect `http://127.0.0.1/callback`, Authorization Code e Refresh Token, **access token JWT**, roles no token. Não há client secret: o `sk` é um cliente público. O client ID é um por ambiente.
- **Cadastro público desligado** na política de login da instância (`allowRegister = false`), que as organizações herdam.
- **Service accounts na organização `core`** (verificadas no Zitadel de dev em 2026-10-11): `core-user-executor` (`ORG_USER_MANAGER` só na organização `register`: cria e remove usuários e concede as roles pelo Project Grant) e `core-user-observer` (`ORG_OWNER_VIEWER` só na `register`, somente leitura); ambos sem papel na `core` (verificado em 2026-10-14) e `core-organization-executor` (papel de instância `IAM_ORG_MANAGER`; será renomeada para `ipm-organization-executor` quando o Executor da Organization for implementado), com as chaves no volume `identity-bootstrap`; cada componente monta só a própria.
- **Nomes (2026-10-14, decisão 0026):** o projeto da organização `core` passou de `smarkee` para `roles` (o ID não muda, então audience, claims e configuração dos componentes seguem valendo). Foi criada a organização `register` (um projeto `users` chegou a ser criado e foi removido na decisão 0027).
- **Autorizações do projeto `roles` na `core`:** só as roles `*.admin`, dos operadores. Usuários cadastrados são autorizados no contexto da `register`.
- **Project Grant `roles` → `register`** (2026-10-14, decisão 0027): delega só as 7 roles de ação do usuário cadastrado; o ID vai em `CORE_ZITADEL_PROJECT_GRANT_ID`.
- **Variáveis da feature User:** `CORE_ZITADEL_REGISTER_ORGANIZATION_ID` (organização `register`), `CORE_ZITADEL_PROJECT_GRANT_ID` e `CORE_ZITADEL_PROJECT_ID`.
- **Roles `*.admin` para operadores:** autorização externa, criada na organização `core` para o usuário da organização `smarkee`.

Para reproduzir pelo console (**Projetos**, **Autorizações**, **Configurações → Login**; os nomes das opções podem diferir um pouco na versão em uso): crie a organização `core`; nela, o projeto `roles` (*Afirmar roles na autenticação* e *Verificar roles na autenticação* ligados) com as roles acima e a aplicação `cli` (nativa, PKCE, tipo de token JWT, redirect e concessões acima); desligue o registro na política de login; e conceda `core.user.admin` e `ipm.organization.admin` aos operadores.

Depois, no host, grave a configuração uma vez (`~/.config/sk/config.toml`) e faça o login:

```bash
cd components/cli
uv run sk init --force --issuer http://ipm-dev.smarkee.com.br:8080 \
  --api-url http://api-dev.smarkee.com.br:8080 \
  --client-id <client-id-da-aplicação-cli> --allow-insecure-http   # dev não tem TLS
uv run sk auth login
```

- Só entra na aplicação quem tem ao menos uma role no projeto (verificação de role). Um operador sem nenhuma role do projeto é recusado no login.
- Use o issuer pelo gateway (`http://ipm-dev.smarkee.com.br:8080`), e não o endereço direto do `identity`: o `iss` dos tokens precisa ser esse endereço.
- O projeto, a aplicação e o client ID ficam gravados no banco do Zitadel. `docker compose down -v` os apaga, e o client ID muda ao recriá-los.
- Resta um projeto `smarkee` antigo na organização `smarkee` (5 roles, aplicação `cli` sem JWT; verificado em 2026-10-11). Ele sai depois de o login pelo projeto novo ser validado.
- O discovery pelo gateway foi verificado com o `sk`. O login completo no navegador contra a aplicação nova ainda não foi executado.

### Conta de bootstrap da plataforma (`platform-bootstrap@smarkee.internal`)

`platform-bootstrap@smarkee.internal` é o usuário de máquina administrativo da instância do Zitadel (`IAM_OWNER`). Ele é usado **somente pela infraestrutura**, para configurar a plataforma no Zitadel: o projeto `roles`, as roles, a aplicação `cli` e um usuário de máquina por Executor, com papel mínimo (por exemplo, `ipm-organization-executor`). **Nenhum serviço de runtime usa essa conta** (decisão 0011): cada Executor tem a sua identidade (`docs/RESOURCE-CONTROL-SECURITY.md`). A chave fica em `/zitadel/bootstrap/service-account-platform-bootstrap.json`, no volume `identity-bootstrap`.

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

## Bootstrap

O estado inicial é configurado, em primeiro lugar, **por variáveis de ambiente ou pela forma mais simples que a ferramenta oferecer**. Arquivo de bootstrap é o último recurso, usado só quando não há alternativa; nesse caso, o serviço guarda o seu **estado inicial declarado** em `bootstrap/`: arquivos direto na raiz da pasta, cada um com o nome do que configura, em formato nativo da ferramenta e sem scripts. Por isso o Zitadel não tem pasta (primeira instância por `ZITADEL_FIRSTINSTANCE_*` e `ZITADEL_DEFAULTINSTANCE_*` em `identity/compose.yaml`), e database, broker e gateway têm:

- database: as variáveis da imagem criam um único banco e usuário; são necessários três bancos com donos próprios, a localidade do `smarkee` e as revogações de `PUBLIC`;
- broker: o `nats-server` não declara Streams por configuração nem por variável, e serviços de runtime não podem criá-los (`docs/NATS.md`);
- gateway: com banco, o Kong só aceita rotas importadas (a configuração declarativa direta vale apenas no modo sem banco). A configuração do servidor (`nats.conf`, `postgresql.conf`, `pg_hba.conf`, `pg_ident.conf`, `kong.conf`) fica fora de `bootstrap/`. Decisão em `.decisions/0005-bootstrap-declarativo-da-infraestrutura.md`.

| Serviço | Fonte | Quem aplica | Quando | Efeito de alterar um arquivo depois |
|---|---|---|---|---|
| database | `bootstrap/gateway.sql`, `smarkee.sql`, `identity.sql`, `core.sql` e `ipm.sql` (papéis de serviço dos módulos `core` e `ipm`: um por componente de cada tipo, inclusive o Publisher do User e o relay da Organization, ainda no desenho anterior) | A própria imagem (`/docker-entrypoint-initdb.d`) | Só na primeira inicialização do volume | Nenhum, até recriar o volume ou aplicar manualmente (pontos de atenção) |
| identity | Sem pasta: variáveis `ZITADEL_FIRSTINSTANCE_*` e `ZITADEL_DEFAULTINSTANCE_*` (nome da instância, marca d'água e textos de e-mail) em `identity/compose.yaml` | `identity-init` (`zitadel init zitadel`: schemas internos) → `identity` (`start-from-setup`) | Só na primeira inicialização da instância | Nenhum, até recriar a instância (`docker compose down -v`) |
| gateway | `bootstrap/routes.yml` (configuração declarativa do Kong) | Cadeia `gateway-migrations-bootstrap` → `-up` → `-finish` → `gateway-import` | A cada `up`, antes do `gateway` | Reimporta; reinicie o `gateway` (pontos de atenção) |
| broker | `bootstrap/<stream>.json` (Stream do JetStream). Os consumers duráveis de cada tipo são das features (`manager/consumers/` e `<módulo>-<tipo>-consumer` no `compose.yaml` delas) | Um serviço `broker-bootstrap-<nome>` por arquivo | A cada `up`, depois que o broker fica saudável | Falha de forma explícita até a alteração deliberada (abaixo) |
| features (fora deste diretório) | `features/core/user/manager/migrations/*.sql` (schema `core`) e `features/ipm/organization/manager/migrations/*.sql` (schema `ipm`): tabelas, views e privilégios no SSOT. O código é do Manager de cada tipo (decisão 0015) | `core-user-migrate` e `ipm-organization-migrate`, no `compose.yaml` da feature (`psql` como o dono `smarkee`, arquivos em ordem) | A cada `up`, depois que o banco fica saudável | Aplicado no próximo `up`; as migrações são idempotentes e seguem expandir → migrar → contrair (`docs/POSTGRESQL.md` §15) |

Os contêineres de inicialização equivalem a *initContainers*: cada um executa um único comando da CLI oficial e termina; o serviço seguinte declara `depends_on` com `service_completed_successfully`.

NATS:

- Os seis Streams operacionais de `docs/NATS.md` são `REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT` e `UPDATED`. O `nats-server` não declara Streams no `nats.conf`; por isso, a criação é pela CLI oficial (imagem mínima `smarkee-nats-client:dev`, em `infrastructure/tools/nats-client`).
- **Todo arquivo novo em `broker/bootstrap/` exige o seu serviço `broker-bootstrap-<stream>`** em `broker/compose.yaml` (âncora `x-broker-bootstrap`); sem ele, o arquivo é ignorado.
- O Stream `ACTION` é **particionado** por `resourceId` (`subject_transform` em `bootstrap/action.json`, 4 partições, decisão 0018): o Subject armazenado ganha o token da partição, e cada Executor tem um consumer por partição. Mudar o número de partições exige recriar o Stream e os consumers.
- Stream inexistente é criado; existente com a mesma configuração não muda. Com configuração diferente, o contêiner falha (`stream name already in use with a different configuration`). Para aplicar a alteração de forma deliberada:

  ```bash
  NATS_PASSWORD=$(grep '^NATS_PASSWORD=' broker/.env | cut -d= -f2)
  docker run --rm --network internal -v "$PWD/broker/bootstrap:/bootstrap:ro" smarkee-nats-client:dev \
    nats -s nats://broker.smarkee.internal:4222 --user smarkee --password "$NATS_PASSWORD" stream edit OBSERVED --config /bootstrap/observed.json --force
  ```

  Campos imutáveis (`retention`, `storage`) não podem ser editados: o Stream precisa ser removido e recriado, com perda das mensagens.
- Os limites são valores de desenvolvimento. `DESIRED` não possui limite de tamanho nem de quantidade total: com descarte do mais antigo, um limite apagaria o estado de outros recursos.
- Os consumers duráveis de cada tipo são das features: os manifestos ficam em `manager/consumers/` e `executor/consumers/`, e o serviço `<módulo>-<tipo>-consumer` do `compose.yaml` da feature os cria (por exemplo, `core-user-manager-{requested,observed,result}` e `core-user-executor-action-p{0..3}`).
- Valores aplicados em dev (`bootstrap/*.json`): todos os Streams em arquivo, 1 réplica, janela de deduplicação de 2 min e `max_msg_size` de 1 MiB. `REQUESTED` e `ACTION`: `workqueue`, `discard new`, 100.000 mensagens e 1 GiB. `DESIRED`: `limits`, 1 mensagem por Subject, `allow_direct`, sem limite de idade. `OBSERVED`: 1 mensagem por Subject, idade máxima de 24 h. `RESULT`: `allow_direct`, 1 GiB, idade máxima de 3 dias. `UPDATED`: 1 GiB, idade máxima de 24 h.
- **Neste diretório, não use `docker compose up -d --wait` sem nomear serviços.** O `--wait` só aceita um contêiner de inicialização terminado quando outro serviço depende dele: ao ver um `broker-bootstrap-*` terminar, ele **interrompe a espera** com `container broker-bootstrap-<stream> exited (0)`, antes de os demais ficarem saudáveis. Use os dois comandos de "Subir e derrubar": o primeiro sobe tudo; o segundo espera somente os serviços de longa duração. Confira a inicialização com `docker compose ps -a` (todos os contêineres de inicialização com `Exited (0)`).

Zitadel: o volume `identity-bootstrap` (`/zitadel/bootstrap` no contêiner) guarda o PAT gerado do cliente de login, que o `identity-login` usa para se autenticar na API do Zitadel, e a chave da conta de bootstrap da plataforma (`service-account-platform-bootstrap.json`). É estado de runtime, e não configuração.

SSOT: num volume do banco já existente, os papéis de `database/bootstrap/core.sql` e `ipm.sql` não são criados sozinhos; aplique os arquivos de bootstrap manualmente (pontos de atenção) antes do primeiro `*-migrate`. Sem os papéis, a migração falha nos `GRANT`.

## Exemplos

PostgreSQL (o banco `smarkee` é o SSOT, conforme `docs/POSTGRESQL.md`; as tabelas dos tipos `core.user` e `ipm.organization` são criadas pelas migrações das features):

```bash
# Com psql instalado no host
psql "postgresql://smarkee:smarkee@localhost:5432/smarkee"
# Sem psql no host: dentro do container (socket local, sem senha)
docker exec -it database.smarkee.internal psql -U smarkee -d smarkee
docker exec -it database.smarkee.internal psql -U postgres            # administrador
```

NATS (sem a CLI `nats` no host, use a imagem mínima `smarkee-nats-client:dev` com a rede do host):

```bash
NATS_PASSWORD=$(grep '^NATS_PASSWORD=' broker/.env | cut -d= -f2)
docker run --rm --network host smarkee-nats-client:dev nats -s nats://localhost:4222 --user smarkee --password "$NATS_PASSWORD" account info
docker run --rm --network host smarkee-nats-client:dev nats -s nats://localhost:4222 --user smarkee --password "$NATS_PASSWORD" stream ls
```

Zitadel e Kong:

```bash
curl -s http://ipm-dev.smarkee.com.br:8080/.well-known/openid-configuration   # discovery OIDC
curl -s http://localhost:8001/services                           # serviços do Kong
curl -s http://localhost:8001/routes                             # rotas do Kong
```

Zitadel direto, sem o gateway (de um container na rede `internal`):

```bash
docker run --rm --network internal curlimages/curl -s -H 'Host: ipm-dev.smarkee.com.br:8080' http://identity.smarkee.internal:8080/.well-known/openid-configuration
```

## Pontos de atenção

- Rotas criadas pelo Kong Manager ficam apenas no banco `gateway`. A cada `up`, o serviço `gateway-import` reimporta `gateway/bootstrap/routes.yml` e pode sobrescrever rotas de mesmo nome; rotas removidas do arquivo não são removidas do banco.
- A reimportação de `gateway/bootstrap/routes.yml` grava direto no banco e **não** invalida o cache de um `gateway` já em execução. Depois de alterar o arquivo, reinicie o gateway: `docker compose up -d && docker compose restart gateway`.
- A inicialização do Zitadel (`identity-init`) e a primeira migração do Kong (`gateway-migrations-bootstrap`) aguardam o PostgreSQL aceitar conexões (`depends_on` com `service_healthy`), declarado no próprio `compose.yaml` de cada recurso, que inclui o `database/compose.yaml`.
- O Kong envia o `X-Forwarded-Host` sem a porta. O login do Zitadel (Next.js) usa esse cabeçalho nos redirecionamentos e o compara com o `Origin` do navegador (proteção das Server Actions). Com o proxy em porta diferente da 80, os redirecionamentos podem perder a porta e o envio do usuário falhar com "erro interno" (`x-forwarded-host ... does not match origin` no log do `identity-login`); isso foi observado quando o proxy estava em outra porta. O login do administrador na porta 8080 foi confirmado no navegador. `KONG_PROXY_HTTP_PORT` e `ZITADEL_EXTERNALPORT` devem permanecer iguais; a instância do Zitadel guarda a porta da primeira inicialização.
- O nome de login do Zitadel é `usuário@domínio-da-organização`. Nesta instância o sufixo da organização está ligado (*Configurações da instância → Domain settings → Add Organization Domain as suffix to loginnames*) e a organização foi renomeada para `smarkee`; por isso `admin` sozinho não é aceito. O administrador entra por `admin@smarkee.internal` (o e-mail) ou `admin@smarkee.ipm-dev.smarkee.com.br`. Essas alterações (sufixo ligado e nome da organização) ficam gravadas no banco do Zitadel: `docker compose down -v` as desfaz, e a instância nova volta aos valores de `identity/.env` (`ZITADEL_FIRSTINSTANCE_*`), com o sufixo desligado. A opção *Organization Domain verification required* deve ficar desligada em dev, pois exige desafio por DNS ou HTTP.
- O Zitadel monta o issuer e as URLs públicas a partir do cabeçalho `x-zitadel-public-host`, preenchido pelo Kong com o `Host` original.
- Os arquivos de `database/bootstrap/` só rodam na primeira inicialização do volume. Em um volume existente, aplique-os manualmente:

  ```bash
  docker exec database.smarkee.internal sh -c 'for f in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f $f; done'
  ```

- As senhas triviais dos bancos `identity` e `gateway` devem ser trocadas antes de qualquer ambiente `stg` ou `prd`.
- O NATS usa um único usuário em dev. A identidade e as permissões por serviço de `docs/NATS.md` e `docs/RESOURCE-CONTROL-SECURITY.md` não são exercitadas aqui; erros de permissão só aparecem em ambientes que as aplicam.
- Na subida a frio, o Kong pode responder 503 (`name resolution failed`) para o login do Zitadel (`identity-login`) por alguns segundos, enquanto expira o cache de DNS negativo de um contêiner que ainda não existia. Normaliza sozinho.
- Desenvolvimento apenas: o Zitadel roda como root, não há TLS e não há arquivamento de WAL (o procedimento de recuperação do SSOT não é testável aqui).
- O PostgreSQL registra esperas por bloqueio (`log_lock_waits`) e comandos acima de 500 ms, sem os valores dos parâmetros: `docker logs database.smarkee.internal`.
- O Kong Manager e a Admin API não têm autenticação; não exponha essas portas fora de `127.0.0.1`.
