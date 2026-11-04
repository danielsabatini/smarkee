# 0107 — Verificação grossa de permissão na borda (gateway) e remoção das permissões `.admin`

- **Data:** 2026-11-03
- **Status:** Aceita e implementada em desenvolvimento (`infrastructure/dev/gateway` e `infrastructure/k8s/platform/gateway`). Revisa a parte da decisão 0052 que mantém as roles fora do gateway ("o gateway só autentica").

## Contexto

A decisão 0052 deixou o gateway apenas autenticando o token. Quem não tem nenhuma permissão do recurso chegava até a API, que o recusava. A decisão 0104 definiu `.operate` como permissão atômica e aposentou `.admin`; o código das APIs ainda aceitava `.admin` por retrocompatibilidade transitória.

## Decisão

- **Verificação grossa na borda, fina na API.** O gateway recusa com `403` o token que não tem **nenhuma** permissão do tipo do recurso. A API continua conferindo a ação, o dono e o estado (verificação fina). A borda nunca concede nada: só nega antes.
- **Como:** plugin `serverless-post-function` (fase `access`), depois do `openid-connect`, que já validou assinatura, emissor, expiração e audiência. A função decodifica o payload do JWT do `Authorization` (sem revalidar a assinatura) e aceita se qualquer claim `urn:zitadel:iam:org:project:*:roles` tiver uma chave com o prefixo do tipo (`permission_prefix`). Assim cobre as permissões de ação (em `roles-<módulo>`) e `operate` (em `roles-operator`), sem IDs de projeto nem variáveis novas.
- **Resposta:** `403` com `{"errorCode":"Forbidden","message":"O solicitante não tem permissão para esta operação."}`, o mesmo contrato do `403` das APIs.
- **Prefixos por rota:** `ipm.organization.`, `ipm.user.`, `ipm.serviceaccount.`, `ipm.permission.`, `ipm.role.`, `ipm.group.`, `sum.`, `bsm.account.`, `bsm.payment.`, `cam.account.`. Rotas anônimas (cadastro e status de registro em `cam`, `identity`, `identity-login`) ficam de fora.
- **Rotas por tipo**, como antes; não há rotas por operação.
- **`.admin` removido das APIs:** só `.operate` vale (decisão 0104). `ipm/permission` passou a exigir `ipm.permission.operate` nas escritas.

## Justificativa

- **Segurança (pilar 1):** defesa em profundidade, no padrão do OWASP Microservices Security Cheat Sheet (autorização grossa na borda, fina no serviço). Quem não tem permissão não alcança a API.
- **Simplicidade (pilar 2):** configuração declarativa no `adc.yaml`, sem rotas por operação e sem novas variáveis. A função Lua é uma âncora YAML reutilizada.

## Alternativas descartadas

- **`claim_schema` do `openid-connect`:** falha devolve `401`, e a ausência de permissão é `403`.
- **`required_scopes`/escopo OAuth:** devolve `403`, mas exigiria escopos novos no Zitadel e no cliente.
- **Rotas por operação:** multiplica rotas e duplica a política da API.
- **Estender a Action `flatRoles`:** acopla a borda ao fluxo de emissão do token e exigiria IDs de projeto.

## Consequências

- **Lua no `adc.yaml`:** a mesma função está em dez rotas e em dois arquivos (`infrastructure/dev/gateway/bootstrap/adc.yaml` e `infrastructure/k8s/platform/gateway/base/adc.yaml`); mantê-los idênticos, salvo os hosts.
- **Prefixo `sum.`:** cobre todas as permissões de `sum`, que hoje são de `sum.service`/`sum.<serviço>`.
- **Novo tipo ou renomeação de permissão** exige atualizar o prefixo da rota. Credenciais salvas com permissões de nome antigo (ex.: `core.account.*`, antes da renomeação para `cam`) passam a tomar `403` na borda em `cam/accounts`.
- **Leitura do próprio registro:** `GET /v1/ipm/users/{id}` e `/v1/ipm/serviceaccounts/{id}` permitiam ao usuário ler o próprio registro sem permissão; um usuário sem nenhuma permissão `ipm.*` agora não alcança esse caminho. Os Receivers parecem reconhecer usuários por projeção, não por HTTP; o impacto não foi verificado em todos os fluxos.
- **Lacuna declarada:** sem `NetworkPolicy`, as APIs podem ser alcançadas direto pelo cluster, sem passar pelo gateway; a borda não é a única barreira, por isso a API continua verificando tudo. Fechar antes do stg (`docs/platform/IMPLEMENTATION-STATUS.md`).
- **Operação:** operadores precisam de `*.operate` no token; o legado `*.admin` deixa de valer.

## Verificação (2026-11-03)

- Lógica Lua isolada: 12 casos (sem header, lixo, sem roles, roles vazio, outro tipo, prefixo parecido, `roles` como string, claim com nome errado, `operate` em outro projeto, `Bearer` minúsculo).
- `adc sync` no gateway de dev (10 rotas atualizadas, `bsm-payment-api` criada). Pelo gateway, com token real: sem permissão do tipo, `403` da borda (`ipm/roles`, `ipm/users`, `ipm/permissions`, `cam/accounts`); com permissão, `200` (`bsm/accounts`, `sum/services`); cadastro anônimo intacto.
- Testes de `tests/api` e `tests/common` das dez features, passando.
- Não verificado: `bsm/payments` pelo gateway de dev devolve `401` porque o `ExternalSecret` vivo do `gateway-secret` não tem `SMARKEE_GATEWAY_AUTH_AUDIENCE_BSM_PAYMENT` (o repositório já o declara; o recurso vivo está desatualizado em relação ao git local).
