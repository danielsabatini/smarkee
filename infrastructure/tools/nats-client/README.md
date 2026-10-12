# smarkee-nats-client

Imagem mínima baseada em Alpine Linux contendo estritamente o binário oficial da CLI `nats`.

## Finalidade

Esta imagem é destinada ao provisionamento declarativo de Streams e Consumers do JetStream (etapa de bootstrap da plataforma e das features). Ela substitui imagens mais pesadas ou toolboxes genéricas, extraindo exclusivamente o executável estático da CLI oficial da Synadia.

## Características

- **Base:** Alpine Linux 3.23 (fixada por `ALPINE_VERSION`).
- **Binário:** `nats` 0.5.0 (fixado por `NATS_CLI_VERSION`), baixado da release oficial do `nats-io/natscli` no GitHub e **verificado pelo `SHA256SUMS`** da release; multi-arquitetura (`amd64` e `arm64`, por `TARGETARCH`).
- **Segurança:** Execução como `10001:10001` (sem privilégios), compatível com `--read-only` e `--cap-drop ALL`. O binário é estático e não resolve o UID pelo `passwd`, por isso a imagem define `USER` e `HOME` por variável de ambiente (sem esse `USER`, a CLI aborta).
- **Shell disponível:** Inclui `/bin/sh` do Alpine para permitir laços e validações encadeadas.
- **Camadas:** multi-stage; a imagem final tem a base e uma camada com o binário (~25 MB). Sem `curl`, `unzip` nem cache de pacotes.
- **Tamanho aproximado:** ~48 MB (contra os ~137 MB da toolbox `nats-box`).

## Construção local

```bash
docker build -t smarkee-nats-client:dev infrastructure/tools/nats-client
# outra versão da CLI: --build-arg NATS_CLI_VERSION=<versão>
```

Uso nos `compose.yaml` (broker e features): `build.context` aponta para este diretório e `image: ${NATS_CLIENT_IMAGE:-smarkee-nats-client:dev}`. A CLI lê `NATS_URL`, `NATS_USER` e `NATS_PASSWORD` do ambiente.

```bash
```
