# Ferramentas da Plataforma (`infrastructure/tools`)

Imagens de contêiner mínimas e utilitárias para a operação, bootstrap e automação do ciclo de vida da plataforma Smarkee.

## Imagens Disponíveis

- **`psql-client/` (`smarkee-psql-client`)**: Imagem mínima com Alpine Linux e `postgresql17-client`, usada para aplicar migrações DDL e rotinas administrativas no SSOT.
- **`nats-client/` (`smarkee-nats-client`)**: Imagem mínima com Alpine Linux e o binário estático oficial do `nats` CLI, usada para provisionar Streams e Consumers no barramento NATS JetStream.

## Diretrizes de Segurança

1. **Menor Privilégio:** Todas as ferramentas executam como usuário sem privilégios (`UID 10001: GID 10001`), nunca como `root`.
2. **Superfície Mínima:** Nenhuma imagem contém daemons ou serviços em segundo plano.
3. **Imagens Leves:** Otimizadas para rápido download e cold-start tanto em ambiente de desenvolvimento local quanto em *initContainers* e *Jobs* de Kubernetes.
