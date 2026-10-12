# syntax=docker/dockerfile:1
# Imagem mínima da CLI `nats` para o bootstrap de Streams e Consumers do JetStream.
#
# - Versão e base fixadas (build reproduzível); o binário é verificado pelo SHA256SUMS da release.
# - Multi-stage: a imagem final leva só o binário estático sobre a base Alpine (sem curl, unzip nem
#   gerenciador de pacotes em camada própria), e roda sem privilégios.
# - Multi-arquitetura: `TARGETARCH` escolhe o binário (amd64 ou arm64).
ARG ALPINE_VERSION=3.23

FROM alpine:${ALPINE_VERSION} AS fetch
ARG NATS_CLI_VERSION=0.5.0
ARG TARGETARCH
WORKDIR /tmp
RUN apk add --no-cache curl unzip \
 && arch="${TARGETARCH:-amd64}" \
 && file="nats-${NATS_CLI_VERSION}-linux-${arch}.zip" \
 && base="https://github.com/nats-io/natscli/releases/download/v${NATS_CLI_VERSION}" \
 && curl -fsSLO "${base}/${file}" \
 && curl -fsSLO "${base}/SHA256SUMS" \
 && grep " ${file}\$" SHA256SUMS | sha256sum -c - \
 && unzip -j "${file}" "nats-${NATS_CLI_VERSION}-linux-${arch}/nats" -d /out \
 && chmod 0555 /out/nats

FROM alpine:${ALPINE_VERSION}
ARG NATS_CLI_VERSION=0.5.0
LABEL org.opencontainers.image.title="smarkee-nats-client" \
      org.opencontainers.image.description="CLI nats para bootstrap de Streams e Consumers" \
      org.opencontainers.image.version="${NATS_CLI_VERSION}"
COPY --from=fetch /out/nats /usr/local/bin/nats
# O binário é estático (sem cgo) e não resolve o UID pelo passwd: sem `USER` definido, a CLI aborta
# ao localizar o diretório de contextos. `HOME` gravável para o contexto da CLI, se usado.
ENV USER=smarkee HOME=/tmp
USER 10001:10001
CMD ["nats", "--help"]
