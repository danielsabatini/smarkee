# Imagem mínima da CLI psql (PostgreSQL) para migrações e comandos administrativos.
# Baseada em Alpine Linux, executa sem privilégios (non-root) e com superfície de ataque mínima.
FROM alpine:3.21

RUN apk add --no-cache --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main postgresql18-client ca-certificates && \
    addgroup -g 10001 smarkee && \
    adduser -u 10001 -G smarkee -s /bin/sh -D smarkee

USER 10001
WORKDIR /migrations

CMD ["psql", "--help"]
