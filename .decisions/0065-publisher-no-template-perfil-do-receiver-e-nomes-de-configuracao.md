# 0065 — Publisher no template, perfil do Receiver e nomes de configuração pela solução

- **Data:** 2026-10-19
- **Status:** Aceita e implementada. Estende a 0064 e aplica o §15.1 do `AGENTS.md` aos contratos de configuração.

## Contexto

A auditoria do `core/account` (2026-10-19) mostrou que o Publisher é igual nas três features, exceto pela validação do envelope, que só o `sum/service` fazia. O `submit` do Receiver e as probes eram iguais no `core/account` e no `ipm/organization`, mas não no `sum/service`, cujo Receiver é outro por desenho (outro repositório e outro identificador de mensagem). Os campos `settings.nats` e `settings.zitadel` e as variáveis `*_NATS_*` e `*_ZITADEL_*` ainda levavam o nome do produto.

## Decisão

- **Publisher no template** (`templates/feature/files/`), na versão do `sum`: a mensagem do outbox é validada contra o envelope antes de sair, e uma recusa é falha permanente (o lote para e o Publisher sai de `ready`, decisão 0018). `core/account` e `ipm/organization` passam a se comportar assim.
- **Perfis opcionais** (`templates/feature/optional/<perfil>/`): arquivos idênticos só nas features que o declaram em `PROFILES` (`sync.py`). O perfil `receiver-http` (`submission.py` e `health_routes.py`) vale para `core/account` e `ipm/organization`; o `sum/service` entra quando o seu Receiver for alinhado.
- **Os demais motores** (Reconciler e handlers do Manager) **não** entram no template: variam no `sum`, e não há evidência de que a quarta feature os repita.
- **`role_config(role)`** em `common/settings.py` substitui o bloco de configuração repetido nos `settings.py` de cada papel.
- **Nomes de configuração:** `settings.messaging` e `settings.identity`; variáveis `<FEATURE>_<PAPEL>_MESSAGING_*` e `<FEATURE>_<PAPEL>_IDENTITY_*`; `CORE_IDENTITY_*` no `.env` da feature; `CONFORMANCE_MESSAGING_*` e `CONFORMANCE_IDENTITY_*` nos e2e.

## Consequências

- **Contrato incompatível** (AGENTS §10): as variáveis antigas deixam de valer. Impacto restrito ao desenvolvimento (compose e `.env` das features); stg e prd ainda não existem. Migração: renomear no `.env` local (feito nos arquivos do repositório). Os recursos da infraestrutura (`NATS_PASSWORD`, `NATS_USER` do servidor de mensageria e as variáveis do Zitadel) mantêm o nome do produto, por serem do próprio produto.
- As decisões anteriores e o CHANGELOG citam os nomes antigos como registro histórico.
