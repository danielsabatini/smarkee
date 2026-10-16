# ipm.organization

A **Organization** é a unidade de isolamento da plataforma (`.decisions/0006-organization-como-unidade-de-isolamento.md`): um recurso do módulo `ipm` (`.decisions/0016-organization-no-modulo-ipm.md`), criado por um usuário registrado (o User, do módulo `core`), que passa a ser o dono dela.

> **Estado: em refação a partir do modelo.** A feature `features/core/user` é o **modelo** (decisão 0015, estrutura da 0017, Publisher da 0019 e Receiver da 0020); a Organization está sendo refeita em fatias. Receiver, Manager (`requested`, `observed` e resultados), Publisher e testes e2e já seguem o modelo; Reconciler, Observer e Executor ainda não existem, então o loop não fecha: a Organization chega a `Pending`, sem ser criada no provedor. As especificações em `docs/` descrevem o alvo, e `docs/IMPLEMENTATION-STATUS.md` registra as lacunas.

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`ipm-organization-receiver`) | Implementado: `POST`, `GET`, lista, `PATCH`, `DELETE` e Operation; e-mail verificado e cota por dono; saúde em `/health/live|ready|startup` |
| Manager | `manager/` (`ipm-organization-manager`) | Implementado: `requested`, `observed` e `completed`/`failed`; nomes reservados, unicidade e cota por dono na unidade atômica |
| Publisher | `publisher/` (`ipm-organization-publisher`) | Implementado (decisão 0019) |
| Reconciler, Observer, Executor | — | **Não implementados** |
| Testes e2e | `tests/e2e/` | 4 testes sem token; 2 exigem `CONFORMANCE_ACCESS_TOKEN` |

O documento de fluxo de dados (`docs/IPM-ORGANIZATION-DATA-FLOW.md`, decisão 0024) **ainda não existe**: nasce quando o loop da Organization fechar.

Contratos em `schemas/ipm/organization/` (índice em `schemas/ipm.organization.index.json`). Papéis de banco: `ipm_organization_manager`, `ipm_organization_receiver` e `ipm_organization_publisher`, em `infrastructure/dev/database/bootstrap/ipm.sql`.

```bash
cd features/ipm/organization && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build                             # exige a plataforma de infrastructure/dev no ar
```
