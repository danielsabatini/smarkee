# Infraestrutura de desenvolvimento

Ambiente local em Docker Compose. **Somente para desenvolvimento**: as credenciais são triviais e as portas ficam presas a `127.0.0.1`, acessíveis apenas na própria máquina.

## Primeira vez: arquivos `.env` e `/etc/hosts`

### 1. Resolução de DNS local (`/etc/hosts`)

O gateway roteia por host e atende o Zitadel em `ipm-dev.smarkee.com.br`. Adicione o apontamento para o loopback no seu arquivo `/etc/hosts`:

```bash
echo "127.0.0.1 ipm-dev.smarkee.com.br" | sudo tee -a /etc/hosts
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

Variáveis adicionais configuradas no `identity/.env`:
- `ZITADEL_FIRSTINSTANCE_INSTANCENAME`: Nome da instância exibido no console (padrão: `IPM`).
- `ZITADEL_FIRSTINSTANCE_ORG_NAME`: Nome da organização inicial (padrão: `smarkee.internal`).
- `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_USERNAME`: Nome do usuário administrador (padrão: `admin`).
- `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_EMAIL`: E-mail do administrador (padrão: `admin@smarkee.internal`).
- `ZITADEL_EXTERNALDOMAIN`: Domínio público de acesso (padrão: `ipm-dev.smarkee.com.br`).
- `ZITADEL_EXTERNALPORT`: Porta pública de acesso (padrão: `8080`, igual a `KONG_PROXY_HTTP_PORT`).

`gateway/.env` não possui valor obrigatório (`KONG_PROXY_HTTP_PORT=8080` por padrão).

## Subir e derrubar

```bash
docker compose up -d                                                 # sobe tudo, inclusive os contêineres de inicialização
docker compose up -d --wait broker gateway identity identity-login   # espera os serviços de longa duração ficarem saudáveis
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
| Cadastro de nova organização (Zitadel) | http://ipm-dev.smarkee.com.br:8080/ui/login/register/org | Nenhuma: página pública que cria a organização e o seu primeiro usuário |
| Kong Manager | http://localhost:8002 | Nenhuma |
| Kong Admin API | http://localhost:8001 | Nenhuma |
| PostgreSQL | `psql "postgresql://smarkee:smarkee@localhost:5432/smarkee"` | Ver "Credenciais" |
| NATS | `nats://smarkee:<NATS_PASSWORD>@localhost:4222` · monitoramento em http://localhost:8222 | `NATS_PASSWORD` de `broker/.env` |

- Use o nome `ipm-dev.smarkee.com.br` **com a porta `:8080`** no navegador. O endereço `localhost:8080` não é roteado (o gateway roteia por host) e responde 404.
- De um contêiner na rede `internal`, use os nomes `*.smarkee.internal` da coluna **Rede `internal`** do mapa abaixo; `localhost` ali aponta para o próprio contêiner.
- Todas as portas são publicadas apenas em `127.0.0.1`.
- **Nome de login no Zitadel:** informe o nome completo, `usuário@domínio-da-organização`, ou o e-mail do usuário. Digitar só `admin` retorna "usuário não encontrado". Para o administrador: `admin@smarkee.internal` ou `admin@smarkee.ipm-dev.smarkee.com.br`. Para usuários de organizações criadas pelo cadastro, o domínio é `<nome-da-organização>.ipm-dev.smarkee.com.br` (por exemplo, `smarkee.ipm-dev.smarkee.com.br`); o e-mail informado no cadastro também funciona. A forma exata para organizações novas não foi testada.
- O cadastro de organização é o do login v1 do Zitadel (`/ui/login/register/org`); o `/ui/v2/login/register` cadastra apenas usuário. A página abre e exibe o formulário, mas o envio do cadastro ainda não foi testado com a porta 8080. A porta faz parte do endereço (`ZITADEL_EXTERNALPORT`); em outros ambientes o endereço será outro.

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
| Kong (proxy HTTPS) | https://localhost:8443 | https://gateway.smarkee.internal:8443 | Certificado autoassinado (`curl -k`); não use para o Zitadel (ver OIDC) · responde 404 sem um host roteado |
| Kong Admin API | http://localhost:8001 · https://localhost:8444 | http://gateway.smarkee.internal:8001 | Sem autenticação |
| Kong Manager | http://localhost:8002 · https://localhost:8445 | — | Navegador; sem autenticação |
| PostgreSQL | `localhost:5432` | `database.smarkee.internal:5432` | Senha obrigatória por TCP (SCRAM) |
| NATS (cliente) | `nats://localhost:4222` | `nats://broker.smarkee.internal:4222` | Usuário e senha obrigatórios |
| NATS (monitoramento) | http://localhost:8222 | http://broker.smarkee.internal:8222 | `/healthz`, `/varz`, `/jsz`; sem autenticação |

O gateway trata somente HTTP e HTTPS e roteia por host: o Zitadel atende `ipm-dev.smarkee.com.br`, e cada nova API recebe um host próprio (por exemplo, `api.localhost`). No host, aponte `127.0.0.1 ipm-dev.smarkee.com.br` em `/etc/hosts`. O NATS e o PostgreSQL são acessados diretamente, sem o gateway.

O proxy HTTP do gateway é publicado na porta 8080 do host (no container, continua na 8000). A porta 80 não é usada porque costuma estar ocupada por outros serviços locais (por exemplo, ingress de clusters Kubernetes locais). O `ZITADEL_EXTERNALPORT` precisa ser igual à porta publicada do proxy (ver pontos de atenção).

Somente o gateway publica portas do Zitadel. O acesso direto ao `identity` e ao `identity-login` existe apenas na rede `internal`, e o Zitadel escolhe a instância pelo domínio, por isso o cabeçalho `Host` é obrigatório e **deve incluir a porta** (`Host: ipm-dev.smarkee.com.br:8080`): sem a porta, o issuer devolvido perde o `:8080` e não confere com o dos tokens emitidos pelo navegador. O navegador (console e login) deve sempre passar pelo gateway: os redirecionamentos e o issuer apontam para `http://ipm-dev.smarkee.com.br:8080`, e só o gateway reúne a API e o login no mesmo domínio.

## Credenciais

Valores sensíveis ficam nos arquivos `.env` (fora do git). As senhas dos bancos de aplicação são triviais e fixas em `database/bootstrap/*.sql`.

| Sistema | Usuário | Senha | Onde está |
|---|---|---|---|
| Zitadel (administrador) | `admin@smarkee.internal` ou `admin@smarkee.ipm-dev.smarkee.com.br` | `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD` | `identity/.env` (troca obrigatória no primeiro acesso) |
| PostgreSQL (administrador) | `postgres` | `POSTGRES_PASSWORD` | `database/.env` |
| PostgreSQL, banco `smarkee` (SSOT, proprietário) | `smarkee` | `smarkee` | `database/bootstrap/smarkee.sql` |
| PostgreSQL, banco `identity` | `identity` | `identity` | `database/bootstrap/identity.sql` (o Zitadel usa só este usuário, sem credencial de administrador) |
| PostgreSQL, banco `gateway` | `gateway` | `gateway` | `database/bootstrap/gateway.sql` |
| PostgreSQL, banco `smarkee` (serviço `core`) | `core_organization_manager_login`, `core_organization_api_login`, `core_relay_login`, `core_maintenance_login` | igual ao usuário | `database/bootstrap/core.sql` |
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

### Login do CLI (`sk auth login`)

O `sk` autentica direto no Zitadel, pelo gateway, sem API própria de autenticação (Authorization Code com PKCE e retorno em `127.0.0.1`; uso em `components/cli/README.md`). Ele usa o projeto da plataforma e a sua aplicação nativa (decisão 0010), criados uma vez pelo console (http://ipm-dev.smarkee.com.br:8080/ui/console/), na organização `smarkee`:

1. **Projetos → Criar projeto**: nome `smarkee`. Nas configurações do projeto, ligue **Afirmar roles na autenticação** (*Assert Roles on Authentication*), para que as roles venham no token.
2. No projeto, **Roles**: crie as chaves `platform.admin` (não delegável), `organization.admin` e `organization.viewer` (delegáveis às organizations por Project Grant).
3. Em **Autorizações** (*Authorizations*), conceda `platform.admin` ao usuário `admin`.
4. No projeto, **Nova aplicação**: nome `cli`, tipo **Nativa**, método de autenticação **PKCE**.
5. **Redirect URI**: `http://127.0.0.1/callback`. A porta não entra: em aplicação nativa, o Zitadel aceita qualquer porta em loopback (RFC 8252, seção 7.3), e o `sk` usa uma porta efêmera a cada login.
6. **Tipos de concessão (grant types)**: **Authorization Code** e **Refresh Token**.
7. Copie o **Client ID** da aplicação e o **ID do projeto** (o serviço `core` usa o ID do projeto para o Project Grant e para validar a audience dos tokens). Não há client secret: o `sk` é um cliente público.

Depois, no host, grave a configuração uma vez (`~/.config/sk/config.toml`) e faça o login:

```bash
cd components/cli
uv run sk auth init --issuer http://ipm-dev.smarkee.com.br:8080 \
  --client-id <client-id-da-aplicação-sk> --allow-insecure-http   # dev não tem TLS
uv run sk auth login
```

O client ID é um por ambiente, e não por organization: usuários de todas as organizations entram pela mesma aplicação `cli`.

- Use o issuer pelo gateway (`http://ipm-dev.smarkee.com.br:8080`), e não o endereço direto do `identity`: o `iss` dos tokens precisa ser esse endereço.
- O projeto, a aplicação e o client ID ficam gravados no banco do Zitadel. `docker compose down -v` os apaga, e o client ID muda ao recriá-los.
- O discovery pelo gateway foi verificado com o `sk`. O login completo no navegador ainda não foi executado contra esta aplicação, e os nomes das opções do console podem diferir um pouco na versão em uso.

### Executor do `core` (usuário de máquina)

O Executor do módulo `core` cria no Zitadel as organizações, os Project Grants e o primeiro usuário de cada Organization (decisões 0010 e 0011). Ele se autentica com um usuário de máquina (`core-executor`) e uma chave JSON, lida pelo serviço `core` em `/zitadel/bootstrap/service-account-core-executor.json`, no volume `identity-bootstrap`.

- **Instância nova** (depois de `docker compose down -v`): o próprio Zitadel cria o usuário e grava a chave, pelas variáveis `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*` e `ZITADEL_FIRSTINSTANCE_MACHINEKEYPATH` de `identity/compose.yaml`. Ele recebe o papel `IAM_OWNER`.
- **Instância existente**: as variáveis não se aplicam. Crie pelo console, uma vez:
  1. na organização `smarkee`, **Usuários → Usuários de serviço → Novo**: nome de usuário `core-executor`, tipo de token de acesso **JWT**;
  2. no usuário, **Chaves → Nova**, tipo **JSON**, com expiração; baixe o arquivo (ele só é exibido uma vez);
  3. em **Configurações padrão → Gerentes** (*Managers* da instância), adicione `core-executor` com o papel `IAM_OWNER`;
  4. copie a chave para o volume e apague a cópia local:

     ```bash
     docker cp <arquivo-baixado>.json identity.smarkee.internal:/zitadel/bootstrap/service-account-core-executor.json
     rm <arquivo-baixado>.json
     ```

- A chave é segredo: nunca a versione nem a copie para fora do volume. O padrão `service-account*.json` está no `.gitignore` como proteção adicional.
- `IAM_OWNER` é mais do que o Executor precisa (ele só cria e gerencia organizações e grants). É aceito em dev; antes de stg e prd, o Executor passa a ser um processo separado com um papel mínimo (decisão 0011).
- A criação automática pela primeira instância ainda não foi verificada (exige recriar a instância). A criação manual segue os nomes do console da versão em uso, que podem diferir um pouco.

## Bootstrap

O estado inicial é configurado, em primeiro lugar, **por variáveis de ambiente ou pela forma mais simples que a ferramenta oferecer**. Arquivo de bootstrap é o último recurso, usado só quando não há alternativa; nesse caso, o serviço guarda o seu **estado inicial declarado** em `bootstrap/`: arquivos direto na raiz da pasta, cada um com o nome do que configura, em formato nativo da ferramenta e sem scripts. Por isso o Zitadel não tem pasta (primeira instância por `ZITADEL_FIRSTINSTANCE_*` e `ZITADEL_DEFAULTINSTANCE_*` em `identity/compose.yaml`), e database, broker e gateway têm:

- database: as variáveis da imagem criam um único banco e usuário; são necessários três bancos com donos próprios, a localidade do `smarkee` e as revogações de `PUBLIC`;
- broker: o `nats-server` não declara Streams por configuração nem por variável, e serviços de runtime não podem criá-los (`docs/NATS.md`);
- gateway: com banco, o Kong só aceita rotas importadas (a configuração declarativa direta vale apenas no modo sem banco). A configuração do servidor (`nats.conf`, `postgresql.conf`, `pg_hba.conf`, `pg_ident.conf`, `kong.conf`) fica fora de `bootstrap/`. Decisão em `.decisions/0005-bootstrap-declarativo-da-infraestrutura.md`.

| Serviço | Fonte | Quem aplica | Quando | Efeito de alterar um arquivo depois |
|---|---|---|---|---|
| database | `bootstrap/gateway.sql`, `smarkee.sql`, `identity.sql`, `core.sql` (papéis do módulo core) | A própria imagem (`/docker-entrypoint-initdb.d`) | Só na primeira inicialização do volume | Nenhum, até recriar o volume ou aplicar manualmente (pontos de atenção) |
| identity | Sem pasta: variáveis `ZITADEL_FIRSTINSTANCE_*` e `ZITADEL_DEFAULTINSTANCE_*` (nome da instância, marca d'água e textos de e-mail) em `identity/compose.yaml` | `identity-init` (`zitadel init zitadel`: schemas internos) → `identity` (`start-from-setup`) | Só na primeira inicialização da instância | Nenhum, até recriar a instância (`docker compose down -v`) |
| gateway | `bootstrap/routes.yml` (configuração declarativa do Kong) | Cadeia `gateway-migrations-bootstrap` → `-up` → `-finish` → `gateway-import` | A cada `up`, antes do `gateway` | Reimporta; reinicie o `gateway` (pontos de atenção) |
| broker | `bootstrap/<stream>.json` (configuração nativa de Stream do JetStream) | Um serviço `broker-bootstrap-<stream>` por arquivo | A cada `up`, depois que o broker fica saudável | Falha de forma explícita até a alteração deliberada (abaixo) |
| core | `features/core/migrations/*.sql` (schema `core`, tabelas, views e privilégios no SSOT) | `core-migrate` (`psql` como o dono `smarkee`, arquivos em ordem) | A cada `up`, depois que o banco fica saudável | Aplicado no próximo `up`; as migrações são idempotentes e seguem expandir → migrar → contrair (`docs/POSTGRESQL.md` §15) |

Os contêineres de inicialização equivalem a *initContainers*: cada um executa um único comando da CLI oficial e termina; o serviço seguinte declara `depends_on` com `service_completed_successfully`.

NATS:

- Os seis Streams operacionais de `docs/NATS.md` são `REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT` e `UPDATED`. O `nats-server` não declara Streams no `nats.conf`; por isso, a criação é pela CLI oficial (`nats-box`).
- **Todo arquivo novo em `broker/bootstrap/` exige o seu serviço `broker-bootstrap-<stream>`** em `broker/compose.yaml` (âncora `x-broker-bootstrap`); sem ele, o arquivo é ignorado.
- Stream inexistente é criado; existente com a mesma configuração não muda. Com configuração diferente, o contêiner falha (`stream name already in use with a different configuration`). Para aplicar a alteração de forma deliberada:

  ```bash
  NATS_PASSWORD=$(grep '^NATS_PASSWORD=' broker/.env | cut -d= -f2)
  docker run --rm --network internal -v "$PWD/broker/bootstrap:/bootstrap:ro" natsio/nats-box:0.20.0-nonroot \
    nats -s nats://broker.smarkee.internal:4222 --user smarkee --password "$NATS_PASSWORD" stream edit OBSERVED --config /bootstrap/observed.json --force
  ```

  Campos imutáveis (`retention`, `storage`) não podem ser editados: o Stream precisa ser removido e recriado, com perda das mensagens.
- Os limites são valores de desenvolvimento. `DESIRED` não possui limite de tamanho nem de quantidade total: com descarte do mais antigo, um limite apagaria o estado de outros recursos.
- Os consumers duráveis de cada tipo de recurso serão declarados quando o tipo for modelado (manifesto por tipo, `docs/NATS.md`).
- **Até existir o primeiro serviço que dependa dos Streams (o Manager), não use `docker compose up -d --wait` sem nomear serviços.** O `--wait` só aceita um contêiner de inicialização terminado quando outro serviço depende dele: ao ver um `broker-bootstrap-*` terminar, ele **interrompe a espera** com `container broker-bootstrap-<stream> exited (0)`, antes de os demais ficarem saudáveis. Use os dois comandos de "Subir e derrubar": o primeiro sobe tudo; o segundo espera somente os serviços de longa duração. Confira a inicialização com `docker compose ps -a` (todos os contêineres de inicialização com `Exited (0)`).

Zitadel: o volume `identity-bootstrap` (`/zitadel/bootstrap` no contêiner) guarda o PAT gerado do cliente de login, que o `identity-login` usa para se autenticar na API, e a chave do Executor do `core` (`service-account-core-executor.json`). É estado de runtime, e não configuração.

SSOT: num volume do banco já existente, os papéis de `database/bootstrap/core.sql` não são criados sozinhos; aplique os arquivos de bootstrap manualmente (pontos de atenção) antes do primeiro `core-migrate`. Sem os papéis, a migração falha nos `GRANT`.

## Exemplos

PostgreSQL (o banco `smarkee` é o SSOT, conforme `docs/POSTGRESQL.md`; ainda não possui tabelas, que serão criadas pelas migrações):

```bash
# Com psql instalado no host
psql "postgresql://smarkee:smarkee@localhost:5432/smarkee"
# Sem psql no host: dentro do container (socket local, sem senha)
docker exec -it database.smarkee.internal psql -U smarkee -d smarkee
docker exec -it database.smarkee.internal psql -U postgres            # administrador
```

NATS (sem a CLI `nats` no host, use o container oficial com a rede do host):

```bash
NATS_PASSWORD=$(grep '^NATS_PASSWORD=' broker/.env | cut -d= -f2)
docker run --rm --network host natsio/nats-box nats -s nats://localhost:4222 --user smarkee --password "$NATS_PASSWORD" account info
docker run --rm --network host natsio/nats-box nats -s nats://localhost:4222 --user smarkee --password "$NATS_PASSWORD" stream ls
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
