# smarkee-psql-client

Imagem mínima baseada em Alpine Linux contendo estritamente a CLI `psql` (PostgreSQL) e runtime de conexão (`libpq`).

## Finalidade

Esta imagem é destinada exclusivamente à execução de scripts de migração DDL (`*.sql`), rotinas de inicialização e comandos administrativos contra o banco de dados do SSOT. Ela substitui o uso da imagem completa do servidor de banco (`postgres:alpine`), reduzindo o tamanho de ~425 MB para ~22 MB e eliminando binários de servidor, extensões e daemons.

## Características

- **Base:** Alpine Linux 3.21.
- **Pacotes instalados:** `postgresql17-client` e `ca-certificates`.
- **Segurança:** Execução obrigatória como usuário não-root `smarkee` (`UID 10001: GID 10001`).
- **Shell disponível:** Inclui `/bin/sh` do Alpine para permitir laços de migração como `for migration in /migrations/*.sql; do psql ...; done`.
- **Tamanho aproximado:** ~22 MB.

## Construção local

```bash
docker build -t smarkee-psql-client:dev infrastructure/tools/psql-client
```
