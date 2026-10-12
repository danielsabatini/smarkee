# Imagem mínima da CLI nats para bootstrap de streams, consumers e comandos administrativos.
# Extrai o binário estático oficial da Synadia sobre base Alpine Linux com usuário não-root.
FROM natsio/nats-box:0.20.0-nonroot AS nats-source

FROM alpine:3.21

RUN apk add --no-cache ca-certificates && \
    addgroup -g 10001 smarkee && \
    adduser -u 10001 -G smarkee -s /bin/sh -D smarkee

COPY --from=nats-source /usr/local/bin/nats /usr/local/bin/nats

USER 10001
WORKDIR /home/smarkee

CMD ["nats", "--help"]
