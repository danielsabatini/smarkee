# 0025 — Roles de ação do User registradas no SSOT

- **Data:** 2026-10-14
- **Status:** Aceita
- **Rotas:** os caminhos citados aqui (`/v1/users`, `/v1/organizations`, `/v1/<tipos>`) foram substituídos pelo padrão da decisão 0030 (`/v1/<módulo>/<tipos>`).
- **Nomes das roles:** os nomes citados aqui (`organization.*`, `user.*`, `platform.admin`) foram substituídos pelo padrão da decisão 0028 (`ipm.organization.*`, `core.user.*`, `*.admin`).

## Contexto

O `platformAccess` do User (`granted` ou `revoked`) diz se o usuário tem autorização no projeto `roles`, mas não diz **quais roles**. O conjunto de roles (decisões 0010 e 0014) vivia em duas configurações separadas: `granted_roles` no Executor e `expected_roles` no Observer. O Observer reduzia as roles lidas do Zitadel a um booleano e descartava a lista. Resultado: nenhum contrato nem linha do SSOT registrava o que o usuário deve ter nem o que ele tem; as duas listas podiam divergir sem aviso; e mudar o conjunto não passava por `desiredGeneration`.

## Decisão

- **`desired.platformRoles`:** lista de roles de ação (`schemas/core/user/desired.v1.schema.json`), em ordem alfabética e sem repetição. É a **intenção**: as roles que o usuário deve ter no projeto da plataforma. Obrigatória. `platformAccess = revoked` implica lista vazia.
- **`observed.platformRoles`:** as roles que o usuário **tem** no projeto, lidas do Zitadel pelo Observer. `observed.platformAccess` é `granted` quando há ao menos uma role.
- **Fonte única do conjunto:** a configuração do Manager (`CORE_USER_MANAGER_PLATFORM_ROLES`, lista em JSON; default: as 7 roles da decisão 0014). O Manager grava o conjunto no `desired` na criação; o `desired` de remoção copia o valor atual. O Executor concede o que está no `desired`; o Observer informa o que existe. Nenhum dos dois tem lista própria.
- **Convergência:** `platformAccess` igual **e** `desired.platformRoles ⊆ observed.platformRoles`. Roles a mais no Zitadel (por exemplo, `platform.admin` concedida a um operador) não são divergência; é a mesma semântica de "ao menos" que o Executor já aplicava. Falta de role gera `update` com `reason = Drift`.
- **Leitura:** `GET /v1/users/{id}` expõe `platformRoles` no `desired` e no `observed`. Roles não são dado pessoal (`internal`).
- **Migração `0002-user-platform-roles.sql`:** preenche o `desired` das linhas anteriores com o conjunto que o usuário já recebia (`granted`) ou com a lista vazia (`revoked`). Só o jsonb muda; sem nova geração.

## Justificativa

- O que o usuário pode fazer é parte do estado do recurso e deve ter intenção, observação e histórico como os demais campos gerenciados (`AGENTS.md` §13 e §14).
- Uma só fonte elimina a divergência entre Executor e Observer e faz a mudança do conjunto passar pelo Manager, com `desiredGeneration`.
- Manter `platformAccess` evita quebrar a Organization e o privilégio de operador (decisão 0010), que dependem do campo; `platformRoles` o detalha.

## Consequências

- **Contrato:** `desired` do User passa a exigir `platformRoles`. Mensagens `desired` já publicadas no stream (geração anterior) não têm o campo: o Executor as rejeita (`Rejected`, sem retentativa) em vez de conceder um conjunto presumido. Em dev, usuários cadastrados antes da mudança precisam de um novo `desired` (recriar o usuário); a migração só corrige o SSOT.
- Mudar `CORE_USER_MANAGER_PLATFORM_ROLES` vale para os **próximos** cadastros. Alterar o acesso de usuários existentes é uma operação de administração, ainda inexistente (abaixo).
- O Observer informa todas as roles do usuário no projeto, e cada uma precisa casar com o padrão de `platformRole` (`^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$`).

## Adiado

- **Revogar ou conceder o acesso de um usuário existente** (`platformAccess = revoked|granted`) é privilégio de operador (`platform.admin`, decisão 0010) e **não** é exposto ao usuário final. Hoje o ramo `revoked` do Executor e o `Drift` do Reconciler existem, mas nada altera o `desired`: `desired_for_update` do Manager rejeita o `update` e o Receiver só tem `POST`, `GET` e `DELETE`. A operação (`PATCH /v1/users/{id}` restrito a `platform.admin`, com `platformRoles` vazio ao revogar) entra junto com as ferramentas de administração da plataforma.
