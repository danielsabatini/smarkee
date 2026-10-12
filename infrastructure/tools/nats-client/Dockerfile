# Imagem mínima da CLI nats para bootstrap de streams, consumers e comandos administrativos.
# Obtém a CLI oficial da Synadia conforme a documentação oficial (https://docs.nats.io/concepts/getting-started/).
ARG NATS_CLI_VERSION=latest

FROM alpine:3.21 AS builder

ARG NATS_CLI_VERSION
RUN apk add --no-cache curl ca-certificates && \
    curl -sf "https://binaries.nats.dev/nats-io/natscli/nats@${NATS_CLI_VERSION}" | sh && \
    mv nats /usr/local/bin/nats

FROM alpine:3.21

RUN apk add --no-cache ca-certificates && \
    addgroup -g 10001 smarkee && \
    adduser -u 10001 -G smarkee -s /bin/sh -D smarkee

COPY --from=builder /usr/local/bin/nats /usr/local/bin/nats

USER 10001
WORKDIR /home/smarkee

CMD ["nats", "--help"]
