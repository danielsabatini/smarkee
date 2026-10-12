# smarkee-nats-client

Imagem mínima baseada em Alpine Linux contendo estritamente o binário oficial da CLI `nats`.

## Finalidade

Esta imagem é destinada ao provisionamento declarativo de Streams e Consumers do JetStream (etapa de bootstrap da plataforma e das features). Ela substitui imagens mais pesadas ou toolboxes genéricas, extraindo exclusivamente o executável estático da CLI oficial da Synadia.

## Características

- **Base:** Alpine Linux 3.21.
- **Binário:** Instalado via script e CDN oficial da Synadia/NATS (`https://binaries.nats.dev/nats-io/natscli/nats@latest`), conforme a [documentação oficial de Getting Started](https://docs.nats.io/concepts/getting-started/).
- **Segurança:** Execução obrigatória como usuário não-root `smarkee` (`UID 10001: GID 10001`).
- **Shell disponível:** Inclui `/bin/sh` do Alpine para permitir laços e validações encadeadas.
- **Tamanho aproximado:** ~66 MB (contra os ~137 MB da toolbox `nats-box`).

## Construção local

```bash
docker build -t smarkee-nats-client:dev infrastructure/tools/nats-client
```
