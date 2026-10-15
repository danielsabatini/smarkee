# 0031 — Roles do operador: escopo `*.admin` mais roles de ação explícitas

- **Data:** 2026-10-15
- **Status:** Aceita. Corrige a premissa da decisão 0027 de que, na `core`, bastavam as roles `*.admin` ao operador.

## Contexto

O Receiver faz duas verificações independentes: a role de ação do token (`core.user.get`, `core.user.delete`, `ipm.organization.*`: **o que** pode fazer) e o alcance (o dono do recurso ou um operador `*.admin`: **em quais**). O operador `admin@smarkee` tinha só `core.user.admin` e `ipm.organization.admin`, e por isso recebia `403` em qualquer leitura ou remoção (verificado no dev: `GET` de usuário e de organizations).

## Alternativas avaliadas (segurança → simplicidade → robustez → disponibilidade)

1. **Operador com `*.admin` mais as roles de ação** (adotada).
2. **`*.admin` implica as roles de ação**, no Receiver (rejeitada).

A opção 2 torna o poder implícito: `*.admin` passaria a significar "tudo, hoje e no futuro", sem permitir operador somente leitura, e uma ação nova nasceria liberada a todo operador (falha aberta). A opção 1 mantém o token como retrato fiel do que o operador pode fazer, permite perfis menores e falha fechada (role esquecida dá `403`, e a conformidade acusa). O Zitadel não tem hierarquia entre roles, e as boas práticas dele mandam verificar roles específicas.

## Decisão

- **Operador = `<módulo>.<tipo>.admin` (escopo) + as roles de ação do tipo que ele exerce.** O Receiver não muda.
- **Operador padrão** (`admin@smarkee`): `core.user.admin`, `core.user.get`, `core.user.delete`, `ipm.organization.admin` e `ipm.organization.create|delete|get|list|update`.
- **Operador somente leitura** (perfil possível): `*.admin` mais `get`/`list`, sem `delete`, `create` nem `update`.
- **Onde fica:** autorização no projeto `roles`, no contexto da organização `core`, dono do projeto (sem Project Grant, portanto sem o teto que limita os usuários cadastrados). Os usuários cadastrados continuam sem nenhuma `*.admin`.
- **Roles de ação novas** (por exemplo, as do SUM) são concedidas ao operador explicitamente.
- **Conformidade** (`identity/conformance`): toda autorização na `core` tem ao menos uma `*.admin` e só roles do conjunto conhecido; o operador padrão tem todas as roles.

## Verificação (Zitadel de dev, 2026-10-15)

Autorização do operador atualizada com `UpdateAuthorization` (API v2). Com uma conta de serviço temporária, de mesmas roles:

| Roles | `GET` user | `GET` organizations | `DELETE` user | `POST` organization |
|---|---|---|---|---|
| só `*.admin` | `403` | `403` | — | — |
| `*.admin` + roles de ação | `200` | `200` (inexistente: `404`) | `202` (testado antes, em usuário temporário; `409` com versão desatualizada) | — |
| `*.admin` + `get`/`list` | `200` | `200` | `403` | `403` |

**Não verificado:** login de navegador do `admin@smarkee` com `sk auth login`; `POST`, `PATCH` e `DELETE` de Organization como operador (o Executor da Organization não roda no dev).
