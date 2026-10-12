# ipm.organization

A **Organization** é a unidade de isolamento da plataforma (`.decisions/0006-organization-como-unidade-de-isolamento.md`): um recurso do módulo `ipm` (`.decisions/0016-organization-no-modulo-ipm.md`), criado por um usuário registrado (o User, do módulo `core`), que passa a ser o dono dela.

> **Estado: desenho anterior, a refazer.** Esta feature foi a primeira fatia e antecede as decisões 0017 a 0020. A feature `features/core/user` é o **modelo** (decisão 0015, estrutura da 0017, Publisher da 0019 e Receiver da 0020); a Organization será refeita a partir dela. Enquanto isso, as especificações em `docs/` descrevem o alvo, e `docs/IMPLEMENTATION-STATUS.md` registra as lacunas.

| Papel | Projeto | Estado | Diferença em relação ao modelo (User) |
|---|---|---|---|
| Receiver | `receiver/` (`ipm-organization-receiver`) | Implementado: `POST`, `GET`, lista, `PATCH`, `DELETE` e Operation; e-mail verificado e cota por dono | Camadas antigas (`app.py`, `repository.py`…); saúde em `/healthz`; sem teste de isolamento do `domain/` |
| Manager | `manager/` (`ipm-organization-manager`) | Implementado só para `requested` (`handler.py`, `policies.py` com SQL misturado à regra) | Faltam `observed` e `completed`/`failed`; sem `domain/` puro; sem saúde |
| Relay do outbox | `relay/` (`ipm-organization-relay`) | Implementado, projeto separado | Será o **Publisher** (decisão 0019), com a estrutura e a saúde do User |
| Reconciler, Observer, Executor | — | **Não implementados** | Dependem do modelo do User |
| Testes e2e | `conformance/` | Implementados (4 testes sem token; 2 exigem `CONFORMANCE_ACCESS_TOKEN`) | A mover para `tests/e2e` |

Contratos em `schemas/ipm/organization/` (índice em `schemas/ipm.organization.index.json`). Papéis de banco: `ipm_organization_manager`, `ipm_organization_receiver` e `ipm_organization_relay` (a renomear para `..._publisher`), em `infrastructure/dev/database/bootstrap/ipm.sql`.

```bash
cd features/ipm/organization && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build                             # exige a plataforma de infrastructure/dev no ar
```
