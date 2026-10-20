# 0043 — Proteção contra exclusão (`deletionProtection`)

- **Data:** 2026-10-16
- **Status:** Aceita e implementada para `ipm.organization` e `core.account`. Origem: decisão 0039 §6. **Revisada pela decisão 0072** no ponto "alterar só a proteção conclui na hora": a alteração percorre o loop como qualquer outra. **Detalhada pela decisão 0074:** a proteção é gravada como metadado `deletionProtection` no Zitadel (organização e usuário) e reconciliada.

## Contexto

Apagar uma Organization remove a organização no Zitadel com todo o conteúdo, sem aviso, e apagar uma Account remove a pessoa. Um `delete` por engano (ou repetido por um automatismo) não tem volta. Uma confirmação só na CLI não protege quem chama a API.

## Decisão

- **Campo `deletionProtection` (booleano) no `desired`**, nos recursos que têm apagar de verdade: Organization e Account. **Nasce `true`**; um registro sem o campo vale como **protegido**.
- **Para apagar, é preciso desproteger antes**: um `update` com `deletionProtection: false`, aceito pelo loop, e só então o `delete`. A proteção é a primeira verificação do `delete`.
- **Onde é verificada** (defesa em duas camadas):
  - o Receiver recusa o `DELETE` com `409 DeletionProtected` (na Account, antes da checagem de recursos atrelados da decisão 0040);
  - o Manager revalida na mesma unidade atômica do `delete` e rejeita a Operation com o motivo `protected` (depois de `not_found` e `conflict`).
- **Quem (des)protege:** o dono, com a mesma regra do `update` (Organization) e a role `core.account.delete` (Account, sem role nova). Na Account, o `PATCH /v1/core/accounts/{id}` é novo e só aceita `deletionProtection`.
- ~~**Alterar só a proteção conclui na hora**~~ (substituído pela decisão 0072: conclui na observação da nova geração): a Operation vira `completed` na própria unidade atômica, com nova geração, e o recurso não volta a `Reconciling` (o campo é da plataforma, não há o que reconciliar no provedor).
- **CLI, um comando por sentido:** `sk ipm organization protect|unprotect --resource-id X` e `sk account protect|unprotect`, com `--wait/--timeout`; pedir o estado que já vale não é erro. `get` mostra `protected`.
- **Fora do escopo:** a ligação de serviço do SUM, porque desabilitar não apaga (é reversível). Reconsiderar se o SUM passar a apagar dados ao desabilitar (decisão 0033).

## Justificativa

- **Segurança:** a proteção vale para qualquer cliente da API, e a revalidação no Manager cobre a corrida entre o pedido e a aplicação.
- **Simplicidade:** um campo no `desired`, sem recurso novo nem estado novo; tirar a proteção é um `update` comum.

## Consequências

- **Mudança de contrato (aditiva):** campo novo opcional em `desired` e nas views, motivo `protected` no enum de `operationStatusReason`, `PATCH` novo da Account. Quem apagava direto passa a desproteger antes: os e2e, a jornada e o `smarkee-dev-cleanup` foram ajustados.
- O Manager exige a migração que inclui `protected` no motivo de rejeição (`core/account` `0006` e `ipm/organization` `0002`).
- Pendência: o `delete` de Organization ainda não exige estar vazia (membros, decisão 0039 §5).
