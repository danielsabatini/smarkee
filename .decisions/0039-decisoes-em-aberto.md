# 0039 — Decisões em aberto, adiadas de propósito

- **Data:** 2026-10-16
- **Status:** Em aberto. Registro do que foi discutido e **ainda não decidido**; cada item vira uma decisão própria quando o gatilho acontecer. Nada aqui está implementado.

## Contexto

Ao fechar a Organization (decisão 0038), sobraram pontos que dependem de definição de produto, de segurança ou de infraestrutura que ainda não existe. Registrá-los aqui evita perdê-los e evita decidir às pressas. A fila de trabalho está no `ROADMAP.md` (horizonte Later).

## 1. Exclusão segura da conta: o que sobrou

A regra "só exclui sem recursos atrelados" e o `sk register get|delete` foram decididos e implementados na decisão 0040. Ficam em aberto:

- **Operador excluir a conta de terceiros:** hoje é recusado (`409 ResourcesNotVerifiable`), porque os módulos só respondem pelo que pertence a quem chama. Precisa de um filtro por dono, só para operadores, nas listas de `ipm` e `sum`.
- **Atomicidade:** um estado "excluindo" que os outros módulos respeitem, para impedir criar recursos entre a verificação e a exclusão.
- **Dados pessoais** que sobram em mensagens e no outbox até a retenção; **sessões e tokens** ativos depois de excluir; confirmação ou reautenticação.
- **Gatilho:** antes de abrir o cadastro a pessoas reais (stg ou prd).

## 2. Papéis menores no Zitadel para a Organization

- O Executor usa `IAM_ORG_MANAGER` e o Observer `IAM_OWNER_VIEWER`, ambos de **instância** (o Zitadel v4.19.4 não tem papel menor para criar e listar organizações). Estreitar com papéis customizados, no padrão do `ORG_USER_CREATOR` (decisão 0032), antes de prd.
- **Gatilho:** antes de prd.

## 3. SUM: kill switch e visão de operador

- Falta uma forma de o operador desligar um serviço para todos e de listar as ligações de qualquer usuário (`sum.service.admin`). Escopo e roles a definir.
- **Gatilho:** quando houver um segundo serviço no catálogo ou um operador real.

## Consequências

- Cada item acima, quando decidido, ganha o seu ADR e sai daqui; o `ROADMAP.md` acompanha.
- Os itens de configuração e segredos (Terraform e OpenBao) já têm a decisão 0037.
