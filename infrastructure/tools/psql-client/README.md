# smarkee-psql-client

Imagem mínima baseada em Alpine Linux contendo estritamente a CLI `psql` (PostgreSQL) e runtime de conexão (`libpq`).

## Finalidade

Esta imagem é destinada exclusivamente à execução de scripts de migração DDL (`*.sql`), rotinas de inicialização e comandos administrativos contra o banco de dados do SSOT. Ela substitui o uso da imagem completa do servidor de banco (`postgres:alpine`), reduzindo o tamanho de ~425 MB para ~28 MB e eliminando binários de servidor, extensões e daemons.

## Características

- **Base:** Alpine Linux 3.23 (fixada por `ALPINE_VERSION`), que já traz `postgresql18-client` 18.6 no repositório estável; **não** se mistura o repositório `edge`.
- **Pacote instalado:** `postgresql18-client`, em uma única camada com `--no-cache`. A versão do cliente acompanha a do servidor (`postgres:18.6-alpine`).
- **Segurança:** Execução como o usuário `smarkee` (`10001:10001`, sem shell de login), compatível com `--read-only` e `--cap-drop ALL`.
- **Shell disponível:** Inclui `/bin/sh` do Alpine para permitir laços de migração como `for migration in /migrations/*.sql; do psql ...; done`.
- **Tamanho aproximado:** ~28 MB.

## Construção local

```bash
docker build -t smarkee-psql-client:dev infrastructure/tools/psql-client
```

Uso nos `compose.yaml` das features (serviço `<módulo>-<tipo>-migrate`): `build.context` aponta para este diretório, `image: ${SMARKEE_DATABASE_CLIENT_IMAGE:-smarkee-psql-client:dev}` e a conexão vem de `PGHOST`, `PGDATABASE`, `PGUSER` e `PGPASSWORD`.

```bash
```
