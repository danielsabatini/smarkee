# 0028 — Padrão de nomes das roles

- **Data:** 2026-10-14
- **Status:** Aceita. Substitui os nomes de roles das decisões 0010, 0014, 0025 e 0027 (`organization.*`, `user.*`, `platform.admin`).

## Contexto

As roles do projeto `roles` (Zitadel) são uma por ação, mas os nomes não diziam a quem pertenciam: `organization.create`, `user.get`, `platform.admin`. Com o `user` do módulo `ipm` e o Service Usage Manager (SUM) a caminho, os nomes colidem, e `platform.admin` mistura "poder sobre qualquer recurso" com "ação".

## Decisão

- **Formato:** `<módulo>.<tipo>.<ação>`, em minúsculas, com exatamente três segmentos separados por ponto. O módulo e o tipo são os de `features/<módulo>/<tipo>` e dos subjects. Fala-se em "módulo" e "tipo", e não em "feature" e "componente" (componente é o papel receiver, manager, executor…).
- **Ações:** vocabulário fechado, igual aos verbos das rotas: `create`, `get`, `list`, `update`, `delete`; `enable` e `disable` no SUM. Uma palavra, sem camelCase.
- **Operador:** `<módulo>.<tipo>.admin` dá alcance sobre qualquer instância do tipo e dispensa cota. Não existe role global de operador: operador de User não é operador de Organization.
- **SUM (exceção documentada):** as roles do Zitadel são planas, então o serviço alvo vai no nome, no lugar do tipo: `sum.<serviço>.enable`, `sum.<serviço>.disable`, `sum.<serviço>.get` (por exemplo, `sum.ipm.enable`).
- **Sem curinga:** `ipm.organization.*` é só notação em documentação. O Receiver compara a role exata.
- **Contrato:** `platformRole` (`schemas/core/user/definitions.v1.schema.json`) valida `^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$`.
- **Zitadel:** o `group` de cada role é o módulo.

| Antes | Depois |
|---|---|
| `organization.create`, `.get`, `.list`, `.update`, `.delete` | `ipm.organization.create`, `.get`, `.list`, `.update`, `.delete` |
| `user.get`, `user.delete` | `core.user.get`, `core.user.delete` |
| `platform.admin` | `core.user.admin` e `ipm.organization.admin` |

## Justificativa

- O dono fica explícito no nome, e a ordem módulo → tipo → ação espelha diretórios, subjects e rotas.
- Operador por tipo segue o menor privilégio.
- Tudo minúsculo e com três segmentos cabe numa regex simples, verificada nos testes de contrato.

## Consequências

- Renomeação em dev: o Receiver de cada tipo, o conjunto padrão do Manager, os schemas e os exemplos, os testes e os docs. A migração `0003-user-platform-roles-names.sql` reescreve `desired.platformRoles` das linhas existentes.
- No Zitadel, a chave da role é imutável: as roles novas foram criadas e as antigas removidas; o Project Grant delega as novas; o operador recebeu `core.user.admin` e `ipm.organization.admin`. Tokens emitidos antes valem com os nomes antigos até expirar.
- Para o SUM, o Project Grant é por organização e não por conta: as roles `ipm.*` delegáveis ao SUM também ficam ao alcance do Executor do User. Tratado pela decisão 0032: um projeto de roles por módulo, cada um com o seu Project Grant, e o papel `ORG_USER_CREATOR` no Executor do User.
