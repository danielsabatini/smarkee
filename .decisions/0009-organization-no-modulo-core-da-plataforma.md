# 0009 — Organization no módulo `core` da plataforma

- **Data:** 2026-10-09
- **Status:** Substituída pela decisão 0016 quanto à Organization (volta ao módulo `ipm`). Continua válido que o User é do módulo `core` (decisão 0014). Mantida como histórico.

## Contexto

A decisão 0006 tornou a Organization a unidade de isolamento: todo recurso isolável carrega `organizationId`, e o ID dela é reutilizado no Zitadel, no OpenBao e no Kubernetes. Os documentos a colocavam no módulo `ipm` (Identity Provider Manager), com subjects `*.ipm.organization.*` e o comando `sk ipm organization`.

Com isso, qualquer módulo futuro (secrets, clusters) dependeria do módulo de identidade só para saber a que Organization pertence. A criação da organização no Zitadel é apenas a materialização da Organization no sistema de identidade, assim como o namespace é a materialização no OpenBao.

## Decisão

- A Organization é um recurso **da plataforma**, no módulo **`core`**:
  - subjects `*.ipm.organization.*`;
  - serviços `srv-ipm-organization-*`;
  - código em `features/core/<tipo>/<papel>` (decisão 0015);
  - comando `sk ipm organization create|get|list|update|delete`.
- `core` é o módulo dos recursos da própria plataforma dos quais os demais dependem. O nome `platform` foi descartado por ser ambíguo com o diretório `platform/`, que reúne capacidades de infraestrutura (database, gateway, vault).
- O **User** também é um recurso do módulo `core` (decisão 0014): é a identidade da plataforma, da qual depende a criação de uma Organization. O módulo `ipm` fica com o que vier depois, como os membros de uma Organization e a configuração de identidade dentro dela.
- Cada Executor escreve em um único sistema externo. O Executor da Organization escreve no Zitadel (decisão 0010); os namespaces derivados são recursos dos próprios módulos, referenciando o `organizationId`.

## Justificativa

- A dependência passa a seguir o sentido correto: os módulos dependem da plataforma, e não de outro módulo.
- O CLI fica coerente: comandos da plataforma (`sk auth`, `sk ipm organization`) e comandos dos módulos (`sk ipm ...`).

## Consequências

- `docs/MESSAGING.md`, `NATS.md`, `RESOURCE-CONTROL-LOOP.md` e `RESOURCE-CONTROL-SECURITY.md` passam a usar `ipm.organization`.
- O SSOT ganha o schema `core` (um schema por módulo, `docs/POSTGRESQL.md`).
