# Infraestrutura de desenvolvimento

Ambiente local em Docker Compose. **Somente para desenvolvimento**: as credenciais são triviais e as portas ficam presas a `127.0.0.1`, acessíveis apenas na própria máquina.

## Primeira vez: arquivos `.env`

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
| `identity/.env` | `ZITADEL_ADMIN_PASSWORD` | Senha inicial do administrador do Zitadel, com maiúscula, minúscula, número e símbolo |
| `identity/.env` | `ZITADEL_LOGIN_SESSION_COOKIE_SECRET` | `openssl rand -hex 32` |

`gateway/.env` não possui valor obrigatório.

## Subir e derrubar

```bash
docker compose up -d                                       # sobe tudo, inclusive os contêineres de inicialização
docker compose up -d --wait broker gateway zitadel-login   # espera os serviços de longa duração ficarem saudáveis
docker compose ps                # estado e saúde
docker compose down              # derruba, preservando os volumes
docker compose down -v           # derruba e APAGA os dados
```

Os contêineres de inicialização permanecem parados (`Exited (0)`) depois de executar, preservando o código de saída e os logs para diagnóstico (`docker compose ps -a`, `docker compose logs <serviço>`). O Compose não os remove automaticamente: não há equivalente ao `docker run --rm`, e o `depends_on: service_completed_successfully` precisa do contêiner encerrado para ler o código de saída. A próxima subida os recria.

Cada serviço também sobe isoladamente em seu próprio diretório (`cd database && docker compose up -d`). Use **um modo por vez**: os nomes dos containers são fixos e conflitam entre os dois modos. Cada recurso tem um único `compose.yaml`. O `identity` e o `gateway` incluem o `database/compose.yaml`: isolados, sobem o PostgreSQL junto e aguardam que ele aceite conexões.

## Mapa de acesso

Do host, use a coluna **Host**. De um container na rede `internal` (por exemplo, um serviço do projeto rodando em Docker), use a coluna **Rede `internal`**: dentro de um container, `localhost` e `*.localhost` apontam para o próprio container.

| Sistema | Host | Rede `internal` | Observação |
|---|---|---|---|
| Zitadel (console) | http://auth.localhost:8000/ui/console/ | — | Navegador, via gateway |
| Zitadel (login) | http://auth.localhost:8000/ui/v2/login/ | — | Navegador, via gateway |
| Zitadel (OIDC e APIs) | http://auth.localhost:8000 | http://gateway:8000 com o cabeçalho `Host: auth.localhost:8000` | Ver a seção OIDC |
| Kong (proxy HTTP) | http://localhost:8000 | http://gateway:8000 | Roteia por host (`gateway/bootstrap/routes.yml`); host desconhecido responde 404 |
| Kong (proxy HTTPS) | https://localhost:8443 | https://gateway:8443 | Certificado autoassinado (`curl -k`); não use para o Zitadel (ver OIDC) |
| Kong Admin API | http://localhost:8001 · https://localhost:8444 | http://gateway:8001 | Sem autenticação |
| Kong Manager | http://localhost:8002 · https://localhost:8445 | — | Navegador; sem autenticação |
| PostgreSQL | `localhost:5432` | `database:5432` | Senha obrigatória por TCP (SCRAM) |
| NATS (cliente) | `nats://localhost:4222` | `nats://broker:4222` | Usuário e senha obrigatórios |
| NATS (monitoramento) | http://localhost:8222 | http://broker:8222 | `/healthz`, `/varz`, `/jsz`; sem autenticação |

O gateway trata somente HTTP e HTTPS e roteia por host: o Zitadel atende `auth.localhost`, e cada nova API recebe um host próprio (por exemplo, `api.localhost`). No host, nomes `*.localhost` resolvem para o loopback, sem editar `/etc/hosts`. O NATS e o PostgreSQL são acessados diretamente, sem o gateway.

## Credenciais

Valores sensíveis ficam nos arquivos `.env` (fora do git). As senhas dos bancos de aplicação são triviais e fixas em `database/bootstrap/*.sql`.

| Sistema | Usuário | Senha | Onde está |
|---|---|---|---|
| Zitadel (administrador) | `zitadel-admin@zitadel.auth.localhost` | `ZITADEL_ADMIN_PASSWORD` | `identity/.env` (troca obrigatória no primeiro acesso) |
| PostgreSQL (administrador) | `postgres` | `POSTGRES_PASSWORD` | `database/.env` |
| PostgreSQL, banco `smarkee` (SSOT, proprietário) | `smarkee` | `smarkee` | `database/bootstrap/smarkee.sql` |
| PostgreSQL, banco `zitadel` | `zitadel` | `zitadel` | `database/bootstrap/zitadel.sql` (o Zitadel usa só este usuário, sem credencial de administrador) |
| PostgreSQL, banco `kong` | `kong` | `kong` | `database/bootstrap/kong.sql` |
| NATS | `NATS_USER` (`smarkee`) | `NATS_PASSWORD` | `broker/.env` (um único usuário em dev, compartilhado pelos serviços) |
| Kong Manager / Admin API | — | — | Sem autenticação (Kong OSS) |

O usuário `smarkee` é o proprietário do SSOT, destinado a migrações (`docs/POSTGRESQL.md`). Os serviços do projeto usarão papéis próprios, criados pelas migrações de cada tipo de recurso.

## Strings de conexão

| Destino | Do host | Da rede `internal` |
|---|---|---|
| SSOT (proprietário) | `postgresql://smarkee:smarkee@localhost:5432/smarkee` | `postgresql://smarkee:smarkee@database:5432/smarkee` |
| NATS | `nats://smarkee:<NATS_PASSWORD>@localhost:4222` | `nats://smarkee:<NATS_PASSWORD>@broker:4222` |

Não há TLS em dev (`sslmode=disable` quando o cliente exigir o parâmetro).

## OIDC (Zitadel)

| Item | Valor |
|---|---|
| Issuer | `http://auth.localhost:8000` |
| Discovery | `http://auth.localhost:8000/.well-known/openid-configuration` |
| JWKS | `http://auth.localhost:8000/oauth/v2/keys` |
| Autorização / token | `http://auth.localhost:8000/oauth/v2/authorize` · `/oauth/v2/token` |

- Use sempre o endereço HTTP da porta 8000. O issuer é derivado do endereço de acesso: pelo HTTPS da porta 8443 ele seria `https://auth.localhost:8443`, e tokens emitidos por um endereço não validam no outro.
- Um serviço em container obtém o discovery e o JWKS por `http://gateway:8000` com o cabeçalho `Host: auth.localhost:8000`, e valida o `iss` contra `http://auth.localhost:8000`.

## Bootstrap

O estado inicial é configurado, em primeiro lugar, **por variáveis de ambiente ou pela forma mais simples que a ferramenta oferecer**. Arquivo de bootstrap é o último recurso, usado só quando não há alternativa; nesse caso, o serviço guarda o seu **estado inicial declarado** em `bootstrap/`: arquivos direto na raiz da pasta, cada um com o nome do que configura, em formato nativo da ferramenta e sem scripts. Por isso o Zitadel não tem pasta (primeira instância por `ZITADEL_FIRSTINSTANCE_*` em `identity/compose.yaml`), e database, broker e gateway têm:

- database: as variáveis da imagem criam um único banco e usuário; são necessários três bancos com donos próprios, a localidade do `smarkee` e as revogações de `PUBLIC`;
- broker: o `nats-server` não declara Streams por configuração nem por variável, e serviços de runtime não podem criá-los (`docs/NATS.md`);
- gateway: com banco, o Kong só aceita rotas importadas (a configuração declarativa direta vale apenas no modo sem banco). A configuração do servidor (`nats.conf`, `postgresql.conf`, `pg_hba.conf`, `pg_ident.conf`, `kong.conf`) fica fora de `bootstrap/`. Decisão em `.decisions/0005-bootstrap-declarativo-da-infraestrutura.md`.

| Serviço | Fonte | Quem aplica | Quando | Efeito de alterar um arquivo depois |
|---|---|---|---|---|
| database | `bootstrap/kong.sql`, `smarkee.sql`, `zitadel.sql` | A própria imagem (`/docker-entrypoint-initdb.d`) | Só na primeira inicialização do volume | Nenhum, até recriar o volume ou aplicar manualmente (pontos de atenção) |
| identity | Sem pasta: variáveis `ZITADEL_FIRSTINSTANCE_*` em `identity/compose.yaml` | `zitadel-init` (`zitadel init zitadel`: schemas internos) → `zitadel-api` (`start-from-setup`) | Só na primeira inicialização da instância | Nenhum, até recriar a instância (`docker compose down -v`) |
| gateway | `bootstrap/routes.yml` (configuração declarativa do Kong) | Cadeia `gateway-migrations-bootstrap` → `-up` → `-finish` → `gateway-import` | A cada `up`, antes do `gateway` | Reimporta; reinicie o `gateway` (pontos de atenção) |
| broker | `bootstrap/<stream>.json` (configuração nativa de Stream do JetStream) | Um serviço `broker-bootstrap-<stream>` por arquivo | A cada `up`, depois que o broker fica saudável | Falha de forma explícita até a alteração deliberada (abaixo) |

Os contêineres de inicialização equivalem a *initContainers*: cada um executa um único comando da CLI oficial e termina; o serviço seguinte declara `depends_on` com `service_completed_successfully`.

NATS:

- Os seis Streams operacionais de `docs/NATS.md` são `REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT` e `UPDATED`. O `nats-server` não declara Streams no `nats.conf`; por isso, a criação é pela CLI oficial (`nats-box`).
- **Todo arquivo novo em `broker/bootstrap/` exige o seu serviço `broker-bootstrap-<stream>`** em `broker/compose.yaml` (âncora `x-broker-bootstrap`); sem ele, o arquivo é ignorado.
- Stream inexistente é criado; existente com a mesma configuração não muda. Com configuração diferente, o contêiner falha (`stream name already in use with a different configuration`). Para aplicar a alteração de forma deliberada:

  ```bash
  NATS_PASSWORD=$(grep '^NATS_PASSWORD=' broker/.env | cut -d= -f2)
  docker run --rm --network internal -v "$PWD/broker/bootstrap:/bootstrap:ro" natsio/nats-box:0.20.0-nonroot \
    nats -s nats://broker:4222 --user smarkee --password "$NATS_PASSWORD" stream edit OBSERVED --config /bootstrap/observed.json --force
  ```

  Campos imutáveis (`retention`, `storage`) não podem ser editados: o Stream precisa ser removido e recriado, com perda das mensagens.
- Os limites são valores de desenvolvimento. `DESIRED` não possui limite de tamanho nem de quantidade total: com descarte do mais antigo, um limite apagaria o estado de outros recursos.
- Os consumers duráveis de cada tipo de recurso serão declarados quando o tipo for modelado (manifesto por tipo, `docs/NATS.md`).
- **Até existir o primeiro serviço que dependa dos Streams (o Manager), não use `docker compose up -d --wait` sem nomear serviços.** O `--wait` só aceita um contêiner de inicialização terminado quando outro serviço depende dele: ao ver um `broker-bootstrap-*` terminar, ele **interrompe a espera** com `container broker-bootstrap-<stream> exited (0)`, antes de os demais ficarem saudáveis. Use os dois comandos de "Subir e derrubar": o primeiro sobe tudo; o segundo espera somente os serviços de longa duração. Confira a inicialização com `docker compose ps -a` (todos os contêineres de inicialização com `Exited (0)`).

Zitadel: o volume `zitadel-bootstrap` (`/zitadel/bootstrap` no contêiner) guarda o PAT gerado do cliente de login, que o `zitadel-login` usa para se autenticar na API. É estado de runtime, e não configuração.

## Exemplos

PostgreSQL (o banco `smarkee` é o SSOT, conforme `docs/POSTGRESQL.md`; ainda não possui tabelas, que serão criadas pelas migrações):

```bash
# Com psql instalado no host
psql "postgresql://smarkee:smarkee@localhost:5432/smarkee"
# Sem psql no host: dentro do container (socket local, sem senha)
docker exec -it database psql -U smarkee -d smarkee
docker exec -it database psql -U postgres            # administrador
```

NATS (sem a CLI `nats` no host, use o container oficial com a rede do host):

```bash
NATS_PASSWORD=$(grep '^NATS_PASSWORD=' broker/.env | cut -d= -f2)
docker run --rm --network host natsio/nats-box nats -s nats://localhost:4222 --user smarkee --password "$NATS_PASSWORD" account info
docker run --rm --network host natsio/nats-box nats -s nats://localhost:4222 --user smarkee --password "$NATS_PASSWORD" stream ls
```

Zitadel e Kong:

```bash
curl -s http://auth.localhost:8000/.well-known/openid-configuration   # discovery OIDC
curl -s http://localhost:8001/services                                # serviços do Kong
curl -s http://localhost:8001/routes                                  # rotas do Kong
```

## Pontos de atenção

- Rotas criadas pelo Kong Manager ficam apenas no banco `kong`. A cada `up`, o serviço `gateway-import` reimporta `gateway/bootstrap/routes.yml` e pode sobrescrever rotas de mesmo nome; rotas removidas do arquivo não são removidas do banco.
- A reimportação de `gateway/bootstrap/routes.yml` grava direto no banco e **não** invalida o cache de um `gateway` já em execução. Depois de alterar o arquivo, reinicie o gateway: `docker compose up -d && docker compose restart gateway`.
- A inicialização do Zitadel (`zitadel-init`) e a primeira migração do Kong (`gateway-migrations-bootstrap`) aguardam o PostgreSQL aceitar conexões (`depends_on` com `service_healthy`), declarado no próprio `compose.yaml` de cada recurso, que inclui o `database/compose.yaml`.
- O Zitadel monta o issuer e as URLs públicas a partir do cabeçalho `x-zitadel-public-host`, preenchido pelo Kong com o `Host` original (com a porta). Sem isso, os endpoints OIDC apontariam para `http://auth.localhost` (porta 80).
- Os arquivos de `database/bootstrap/` só rodam na primeira inicialização do volume. Em um volume existente, aplique-os manualmente:

  ```bash
  docker exec database sh -c 'for f in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f $f; done'
  ```

- As senhas triviais dos bancos `zitadel` e `kong` devem ser trocadas antes de qualquer ambiente `stg` ou `prd`.
- O NATS usa um único usuário em dev. A identidade e as permissões por serviço de `docs/NATS.md` e `docs/RESOURCE-CONTROL-SECURITY.md` não são exercitadas aqui; erros de permissão só aparecem em ambientes que as aplicam.
- Na subida a frio, o Kong pode responder 503 (`name resolution failed`) para o login do Zitadel por alguns segundos, enquanto expira o cache de DNS negativo de um contêiner que ainda não existia. Normaliza sozinho.
- Desenvolvimento apenas: o Zitadel roda como root, não há TLS e não há arquivamento de WAL (o procedimento de recuperação do SSOT não é testável aqui).
- O PostgreSQL registra esperas por bloqueio (`log_lock_waits`) e comandos acima de 500 ms, sem os valores dos parâmetros: `docker logs database`.
- O Kong Manager e a Admin API não têm autenticação; não exponha essas portas fora de `127.0.0.1`.
