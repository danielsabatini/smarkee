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
- **Resolvido em 2026-10-18 (decisão 0060):** os papéis de instância ficam como estão, por exceção deliberada, porque o padrão do Zitadel não tem papel menor.

## 3. SUM: kill switch e visão de operador

- Falta uma forma de o operador desligar um serviço para todos e de listar as ligações de qualquer usuário (`sum.service.admin`). Escopo e roles a definir.
- **Gatilho:** quando houver um segundo serviço no catálogo ou um operador real.

## 4. Simplificar mais a CLI

Princípio: quanto menos decisão na mão de quem usa, melhor. Ficam como estão por ora, e a revisar quando a CLI for ao primeiro uso real:

- esperar sempre a convergência (sem `--wait` e `--timeout`) e, com isso, renovar a sessão sozinho (sem `sk auth refresh`);
- `--yes` do `sk register delete` como confirmação interativa quando houver terminal;
- o arquivo `config.toml` e o `sk config`, se dev e stg usarem só variáveis.

## 5. Administradores da Organization

**Fechado pela decisão 0077** (2026-10-20): modelo das clouds, com a conta dona da Organization como root e usuários próprios da Organization (`ipm.user`), sem administrador de negócio separado. O texto abaixo é o histórico da direção anterior.

Direção combinada (2026-10-16): o acesso de uma pessoa a uma Organization passa a ser um recurso da plataforma, criado e removido pela CLI, e não uma permissão dada direto no Zitadel. O dono é o primeiro **administrador**, criado junto com a Organization. *(Termo revisto em 2026-10-20, decisão 0076: o que aqui se chamava "membro" é o **administrador** da Organization; "membro" não é mais usado.)*

- **Definido:**
  - uma Organization sempre tem ao menos um administrador: o último não se remove;
  - apagar a Organization exige que ela esteja **vazia**: sem outros administradores nem usuários, sem recursos de outros módulos e sem conteúdo no Zitadel (a API v2 enxerga usuários e projetos dentro da organização, e o `DeleteOrganization` apaga tudo sem avisar, medido no dev). Com o dono sozinho, ele pode apagar, e o vínculo dele some junto;
  - a verificação tem duas camadas: o Receiver recusa (`409`) usando o que o Observer publica no `observed`, e o Executor revalida contra o Zitadel antes de chamar o `DeleteOrganization`, como última barreira.
- **Em aberto:** quem pode ser administrador (conta já cadastrada, identificada por e-mail, é a recomendação); o nome do comando; quais papéis nativos de administração do Zitadel a plataforma permite; a regra de acesso do Receiver passar de `ownerAccountId` para "é administrador, com este papel"; e medir na API v2 os filtros de administradores e de Project Grants (o formato que usei na sondagem estava errado).

## 6. Proteção contra exclusão (`deletionProtection`)

- **Decidido e implementado** na decisão 0043 (Organization e Account; o SUM fica de fora porque desabilitar não apaga).
- **Em aberto:** a regra "apagar a Organization só vazia" (sem outros administradores nem usuários, sem recursos de outros módulos) depende dos administradores e dos usuários (§5).

## Consequências

- Cada item acima, quando decidido, ganha o seu ADR e sai daqui; o `ROADMAP.md` acompanha.
- Os itens de configuração e segredos (Terraform e OpenBao) já têm a decisão 0037.
