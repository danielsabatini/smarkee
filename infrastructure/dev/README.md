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
| `identity/.env` | `POSTGRES_ADMIN_PASSWORD` | **O mesmo** valor de `POSTGRES_PASSWORD` de `database/.env` |
| `identity/.env` | `ZITADEL_ADMIN_PASSWORD` | Senha inicial do administrador do Zitadel, com maiúscula, minúscula, número e símbolo |
| `identity/.env` | `ZITADEL_LOGIN_SESSION_COOKIE_SECRET` | `openssl rand -hex 32` |

`gateway/.env` não possui valor obrigatório.

## Subir e derrubar

```bash
docker compose up -d --wait      # sobe tudo (database, broker, identity, gateway)
docker compose ps                # estado e saúde
docker compose down              # derruba, preservando os volumes
docker compose down -v           # derruba e APAGA os dados
```

Cada serviço também sobe isoladamente em seu próprio diretório (`cd database && docker compose up -d`). Use **um modo por vez**: os nomes dos containers são fixos e conflitam entre os dois modos. O `identity` e o `gateway` precisam do `database` em execução.

## Mapa de acesso

Do host, use a coluna **Host**. De um container na rede `internal` (por exemplo, um serviço do projeto rodando em Docker), use a coluna **Rede `internal`**: dentro de um container, `localhost` e `*.localhost` apontam para o próprio container.

| Sistema | Host | Rede `internal` | Observação |
|---|---|---|---|
| Zitadel (console) | http://auth.localhost:8000/ui/console/ | — | Navegador, via gateway |
| Zitadel (login) | http://auth.localhost:8000/ui/v2/login/ | — | Navegador, via gateway |
| Zitadel (OIDC e APIs) | http://auth.localhost:8000 | http://gateway:8000 com o cabeçalho `Host: auth.localhost:8000` | Ver a seção OIDC |
| Kong (proxy HTTP) | http://localhost:8000 | http://gateway:8000 | Roteia por host (`gateway/kong.yml`); host desconhecido responde 404 |
| Kong (proxy HTTPS) | https://localhost:8443 | https://gateway:8443 | Certificado autoassinado (`curl -k`); não use para o Zitadel (ver OIDC) |
| Kong Admin API | http://localhost:8001 · https://localhost:8444 | http://gateway:8001 | Sem autenticação |
| Kong Manager | http://localhost:8002 · https://localhost:8445 | — | Navegador; sem autenticação |
| PostgreSQL | `localhost:5432` | `database:5432` | Senha obrigatória por TCP (SCRAM) |
| NATS (cliente) | `nats://localhost:4222` | `nats://broker:4222` | Usuário e senha obrigatórios |
| NATS (monitoramento) | http://localhost:8222 | http://broker:8222 | `/healthz`, `/varz`, `/jsz`; sem autenticação |

O gateway trata somente HTTP e HTTPS e roteia por host: o Zitadel atende `auth.localhost`, e cada nova API recebe um host próprio (por exemplo, `api.localhost`). No host, nomes `*.localhost` resolvem para o loopback, sem editar `/etc/hosts`. O NATS e o PostgreSQL são acessados diretamente, sem o gateway.

## Credenciais

Valores sensíveis ficam nos arquivos `.env` (fora do git). As senhas dos bancos de aplicação são triviais e fixas em `database/initdb/*.sql`.

| Sistema | Usuário | Senha | Onde está |
|---|---|---|---|
| Zitadel (administrador) | `zitadel-admin@zitadel.auth.localhost` | `ZITADEL_ADMIN_PASSWORD` | `identity/.env` (troca obrigatória no primeiro acesso) |
| PostgreSQL (administrador) | `postgres` | `POSTGRES_PASSWORD` | `database/.env` |
| PostgreSQL, banco `smarkee` (SSOT, proprietário) | `smarkee` | `smarkee` | `database/initdb/smarkee.sql` |
| PostgreSQL, banco `zitadel` | `zitadel` | `zitadel` | `database/initdb/zitadel.sql` |
| PostgreSQL, banco `kong` | `kong` | `kong` | `database/initdb/kong.sql` |
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

- Rotas criadas pelo Kong Manager ficam apenas no banco `kong`. A cada `up`, o serviço `gateway-migrations` reimporta `gateway/kong.yml` e pode sobrescrever rotas de mesmo nome; rotas removidas do arquivo não são removidas do banco.
- A reimportação de `gateway/kong.yml` grava direto no banco e **não** invalida o cache de um `gateway` já em execução. Depois de alterar o arquivo, reinicie o gateway: `docker compose up -d --wait && docker compose restart gateway`.
- Na subida pela raiz, `identity/compose.root.yaml` e `gateway/compose.root.yaml` fazem o Zitadel e as migrações do Kong aguardarem o PostgreSQL aceitar conexões. No modo isolado, essa ordem não existe: suba o `database` antes.
- O Zitadel monta o issuer e as URLs públicas a partir do cabeçalho `x-zitadel-public-host`, preenchido pelo Kong com o `Host` original (com a porta). Sem isso, os endpoints OIDC apontariam para `http://auth.localhost` (porta 80).
- Os scripts de `database/initdb/` só rodam na primeira inicialização do volume. Em um volume existente, aplique-os manualmente:

  ```bash
  docker exec database sh -c 'for f in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f $f; done'
  ```

- As senhas triviais dos bancos `zitadel` e `kong` devem ser trocadas antes de qualquer ambiente `stg` ou `prd`.
- O NATS usa um único usuário em dev. A identidade e as permissões por serviço de `docs/NATS.md` e `docs/RESOURCE-CONTROL-SECURITY.md` não são exercitadas aqui; erros de permissão só aparecem em ambientes que as aplicam.
- Na subida a frio, o Kong pode responder 503 (`name resolution failed`) para o login do Zitadel por alguns segundos, enquanto expira o cache de DNS negativo de um contêiner que ainda não existia. Normaliza sozinho.
- Desenvolvimento apenas: o Zitadel roda como root, não há TLS e não há arquivamento de WAL (o procedimento de recuperação do SSOT não é testável aqui).
- O PostgreSQL registra esperas por bloqueio (`log_lock_waits`) e comandos acima de 500 ms, sem os valores dos parâmetros: `docker logs database`.
- O Kong Manager e a Admin API não têm autenticação; não exponha essas portas fora de `127.0.0.1`.
