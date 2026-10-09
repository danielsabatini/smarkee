# 0009 — Organization no módulo `core` da plataforma

- **Data:** 2026-10-09
- **Status:** Aceita. Substitui o módulo `ipm` citado para a Organization na decisão 0006 (o restante da 0006 continua válido).

## Contexto

A decisão 0006 tornou a Organization a unidade de isolamento: todo recurso isolável carrega `organizationId`, e o ID dela é reutilizado no Zitadel, no OpenBao e no Kubernetes. Os documentos a colocavam no módulo `ipm` (Identity Provider Manager), com subjects `*.ipm.organization.*` e o comando `sk ipm organization`.

Com isso, qualquer módulo futuro (secrets, clusters) dependeria do módulo de identidade só para saber a que Organization pertence. A criação da organização no Zitadel é apenas a materialização da Organization no sistema de identidade, assim como o namespace é a materialização no OpenBao.

## Decisão

- A Organization é um recurso **da plataforma**, no módulo **`core`**:
  - subjects `*.core.organization.*`;
  - serviços `srv-core-organization-*`;
  - código em `features/core`;
  - comando `sk organization create|get|list|update|delete`.
- `core` é o módulo dos recursos da própria plataforma dos quais os demais dependem. O nome `platform` foi descartado por ser ambíguo com o diretório `platform/`, que reúne capacidades de infraestrutura (database, gateway, vault).
- O módulo `ipm` fica com os recursos de identidade **dentro** de uma Organization (por exemplo, `sk ipm user`).
- Cada Executor escreve em um único sistema externo. O Executor da Organization escreve no Zitadel (decisão 0010); os namespaces derivados são recursos dos próprios módulos, referenciando o `organizationId`.

## Justificativa

- A dependência passa a seguir o sentido correto: os módulos dependem da plataforma, e não de outro módulo.
- O CLI fica coerente: comandos da plataforma (`sk auth`, `sk organization`) e comandos dos módulos (`sk ipm ...`).

## Consequências

- `docs/MESSAGING.md`, `NATS.md`, `RESOURCE-CONTROL-LOOP.md` e `RESOURCE-CONTROL-SECURITY.md` passam a usar `core.organization`.
- O SSOT ganha o schema `core` (um schema por módulo, `docs/POSTGRESQL.md`).
