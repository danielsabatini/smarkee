# 0030 — Rotas da API com o prefixo do módulo

- **Data:** 2026-10-15
- **Status:** Aceita. Substitui os caminhos `/v1/users`, `/v1/organizations` e `/v1/<tipos>` das decisões 0014, 0015, 0020 e 0025.

## Contexto

As rotas dos Receivers eram `/v1/users` e `/v1/organizations`, sem o módulo. Tudo o mais já carrega o módulo: o diretório da feature (`features/core/user`), os schemas (`core.user_v1`), os subjects e as roles (`core.user.*`, decisão 0028). Com o `ipm` ganhando um `user` próprio (os usuários de dentro da organização criada, distintos do usuário cadastrado do `core`) e com o SUM a caminho, `/v1/users` deixaria de dizer de qual recurso se trata.

## Decisão

- **Padrão:** `/v1/<módulo>/<tipos>`, com o tipo no **plural** do `resourceType`, em minúsculas. Os subcaminhos seguem o recurso: `/v1/<módulo>/<tipos>/{resourceId}` e `/v1/<módulo>/<tipos>/{resourceId}/operations/{operationId}`.
- **Rotas atuais:**

  | Antes | Depois |
  |---|---|
  | `/v1/users` | `/v1/core/users` |
  | `/v1/organizations` | `/v1/ipm/organizations` |

- **Versão:** `v1` continua sendo a versão do contrato da plataforma (nossa), independente da versão da API do Zitadel (decisão 0029).
- **Roteamento:** o gateway roteia por prefixo de módulo e tipo (`~/v1/core/users`, `~/v1/ipm/organizations`); cada Receiver atende só o próprio prefixo.
- **Futuro:** `/v1/ipm/users` (usuários da organização) e `/v1/sum/services` (SUM) seguem o mesmo padrão.

## Consequências

- **Contrato alterado, sem compatibilidade:** não há consumidor externo (pré-lançamento). O gateway não mantém as rotas antigas; quem as chamar recebe `404` do Kong. CLI, OpenAPI, schemas (descrições), testes, gateway e documentação foram atualizados.
- Os identificadores internos (nomes de schema, subjects, parâmetros `user_id` e `organization_id`) não mudam.
