# Infraestrutura de desenvolvimento

Ambiente local em Docker Compose. **Somente para desenvolvimento**: as credenciais são triviais e as portas ficam presas a `127.0.0.1`, acessíveis apenas na própria máquina.

## Subir e derrubar

```bash
# Primeira vez: criar o .env de cada serviço a partir do exemplo e preencher os valores obrigatórios
for s in database broker identity gateway; do cp -n $s/.env.example $s/.env; done

docker compose up -d --wait      # sobe tudo (database, broker, identity, gateway)
docker compose ps                # estado e saúde
docker compose down              # derruba, preservando os volumes
docker compose down -v           # derruba e APAGA os dados
```

Cada serviço também sobe isoladamente em seu próprio diretório (`cd database && docker compose up -d`). Use **um modo por vez**: os nomes dos containers são fixos e conflitam entre os dois modos. O `identity` e o `gateway` precisam do `database` em execução.

## Mapa de acesso

| Sistema | Endereço no host | Como acessar |
|---|---|---|
| Zitadel (console) | http://localhost:8000/ui/console/ | Navegador, via gateway |
| Zitadel (login) | http://localhost:8000/ui/v2/login/ | Navegador, via gateway |
| Kong (proxy HTTP/HTTPS) | http://localhost:8000 · https://localhost:8443 | Rotas declaradas em `gateway/kong.yml` |
| Kong Manager (interface web) | http://localhost:8002 (HTTPS: https://localhost:8445) | Navegador; sem autenticação |
| Kong Admin API | http://localhost:8001 (HTTPS: https://localhost:8444) | `curl http://localhost:8001/routes` |
| PostgreSQL | `localhost:5432` | Cliente SQL (veja abaixo) |
| NATS (cliente) | `nats://localhost:4222` | Cliente NATS |
| NATS (monitoramento) | http://localhost:8222 | `curl http://localhost:8222/healthz`, `/varz`, `/jsz` |

O gateway trata somente HTTP e HTTPS. O NATS e o PostgreSQL são acessados diretamente.

## Credenciais

Valores sensíveis ficam nos arquivos `.env` (fora do git). Os valores abaixo de bancos de aplicação são triviais e fixos em `database/initdb/*.sql`.

| Sistema | Usuário | Senha | Onde está |
|---|---|---|---|
| Zitadel (administrador) | `zitadel-admin@zitadel.localhost` | `ZITADEL_ADMIN_PASSWORD` | `identity/.env` (troca obrigatória no primeiro acesso) |
| PostgreSQL (administrador) | `postgres` | `POSTGRES_PASSWORD` | `database/.env` |
| PostgreSQL, banco `smarkee` (SSOT, proprietário) | `smarkee_owner` | `smarkee` | `database/initdb/smarkee.sql` |
| PostgreSQL, banco `zitadel` | `zitadel` | `zitadel` | `database/initdb/zitadel.sql` |
| PostgreSQL, banco `kong` | `kong` | `kong` | `database/initdb/kong.sql` |
| Kong Manager / Admin API | — | — | Sem autenticação (Kong OSS) |
| NATS | — | — | Sem autenticação |

## Exemplos

PostgreSQL (o banco `smarkee` é o SSOT, conforme `docs/POSTGRESQL.md`; ainda não possui tabelas, que serão criadas pelas migrações):

```bash
# Com psql instalado no host
PGPASSWORD=zitadel psql -h localhost -U zitadel -d zitadel
# Sem psql no host: dentro do container (socket local, sem senha)
docker exec -it database psql -U smarkee_owner -d smarkee
```

NATS (sem a CLI `nats` no host, use o container oficial com a rede do host):

```bash
docker run --rm --network host natsio/nats-box nats -s nats://localhost:4222 account info
docker run --rm --network host natsio/nats-box nats -s nats://localhost:4222 stream ls
```

Kong:

```bash
curl -s http://localhost:8001/services          # serviços
curl -s http://localhost:8001/routes            # rotas
```

## Pontos de atenção

- Rotas criadas pelo Kong Manager ficam apenas no banco `kong`. A cada `up`, o serviço `gateway-migrations` reimporta `gateway/kong.yml` e pode sobrescrever rotas de mesmo nome; rotas removidas do arquivo não são removidas do banco.
- Os scripts de `database/initdb/` só rodam na primeira inicialização do volume. Em um volume existente, aplique-os manualmente:

  ```bash
  docker exec database sh -c 'for f in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f $f; done'
  ```

- As senhas triviais dos bancos `zitadel` e `kong` devem ser trocadas antes de qualquer ambiente `stg` ou `prd`.
- O Kong Manager e a Admin API não têm autenticação; não exponha essas portas fora de `127.0.0.1`.
