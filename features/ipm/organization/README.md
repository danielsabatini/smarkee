# ipm.organization

A **Organization** é a unidade de isolamento da plataforma (`.decisions/0006-organization-como-unidade-de-isolamento.md`): um recurso do módulo `ipm` (`.decisions/0016-organization-no-modulo-ipm.md`), criado por um usuário registrado (o User, do módulo `core`), que passa a ser o dono dela.

> **Estado: loop completo, documentação em refação.** A feature `features/core/user` é o **modelo** (decisão 0015, estrutura da 0017, Publisher da 0019 e Receiver da 0020). Os seis papéis existem e o loop fecha em dev contra o Zitadel: a Organization é criada, renomeada, desativada/reativada (`platformAccess`) e removida pelo próprio loop. O documento de fluxo de dados (`docs/IPM-ORGANIZATION-DATA-FLOW.md`, decisão 0024) e as seções completas deste README ainda estão por escrever.

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`ipm-organization-receiver`) | Implementado: `POST`, `GET`, lista, `PATCH`, `DELETE` e Operation; e-mail verificado e cota por dono; saúde em `/health/live|ready|startup` |
| Manager | `manager/` (`ipm-organization-manager`) | Implementado: `requested`, `observed` e `completed`/`failed`; nomes reservados, unicidade e cota por dono na unidade atômica |
| Publisher | `publisher/` (`ipm-organization-publisher`) | Implementado (decisão 0019) |
| Reconciler | `reconciler/` (`ipm-organization-reconciler`) | Implementado: compara `name` e `platformAccess` e decide `create`, `update` ou `delete` |
| Observer | `observer/` (`ipm-organization-observer`) | Implementado: lê a organização no Zitadel (conta `IAM_OWNER_VIEWER`, somente leitura) |
| Executor | `executor/` (`ipm-organization-executor`) | Implementado: escreve só a organização no Zitadel (conta `IAM_ORG_MANAGER`), sem Project Grant |
| Testes e2e | `tests/e2e/` | Contrato, loop completo e resiliência (`E2E_CHAOS=1`); 2 testes exigem `CONFORMANCE_ACCESS_TOKEN` |

Contratos em `schemas/ipm/organization/` (índice em `schemas/ipm.organization.index.json`). Papéis de banco: `ipm_organization_manager`, `ipm_organization_receiver` e `ipm_organization_publisher`, em `infrastructure/dev/database/bootstrap/ipm.sql`.

```bash
cd features/ipm/organization && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build                             # exige a plataforma de infrastructure/dev no ar
```
