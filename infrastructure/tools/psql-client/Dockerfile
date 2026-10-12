# syntax=docker/dockerfile:1
# Imagem mínima da CLI `psql` (cliente PostgreSQL 18) para migrações e comandos administrativos.
#
# - Base Alpine 3.23, que já traz `postgresql18-client` no repositório estável (sem misturar o
#   repositório `edge`, que quebra a reprodutibilidade e o ABI da base).
# - Uma única camada de pacote (`--no-cache`, sem índice nem cache do apk) e execução sem privilégios.
# - Só o cliente: sem servidor, extensões nem daemons.
ARG ALPINE_VERSION=3.23
FROM alpine:${ALPINE_VERSION}

LABEL org.opencontainers.image.title="smarkee-psql-client" \
      org.opencontainers.image.description="Cliente psql 18 para migrações do SSOT"

RUN apk add --no-cache postgresql18-client \
 && adduser -D -H -u 10001 -s /sbin/nologin smarkee

USER 10001:10001
WORKDIR /migrations
CMD ["psql", "--help"]
