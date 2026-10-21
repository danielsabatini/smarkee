# 0016 — Organization no módulo `ipm`

- **Data:** 2026-10-10
- **Status:** Aceita. Substitui a decisão 0009 (Organization no módulo `core`); o restante da 0009 (o User em `core`) continua válido.

## Contexto

A decisão 0009 colocou a Organization em `core` porque, naquele desenho, a Organization era o primeiro recurso e os demais módulos dependiam dela. A direção mudou (decisões 0013 e 0014): a identidade da plataforma é o **User**, que se cadastra sozinho, e a Organization só é criada por um usuário registrado e autenticado, que passa a ser o dono dela. A dependência agora vai da Organization para o User (`ownerUserId`), e a criação inicial de uma Organization deixou de ser um passo de bootstrap da plataforma.

A Organization, por sua vez, é a materialização da identidade no sistema de identidade (organização e Project Grant no Zitadel), que é o que o módulo `ipm` (Identity Provider Manager) representa.

## Decisão

- **User fica em `core`; Organization volta para `ipm`.**
  - `core`: recursos que existem antes de qualquer Organization (hoje, o User). Subjects `*.core.user.*`, schema `core`, comandos `sk register` e `sk user`.
  - `ipm`: a Organization e o que vier dela (por exemplo, administradores, usuários e configuração de identidade dentro dela). Subjects `*.ipm.organization.*`, schema `ipm`, comando `sk ipm organization`.
- **Componentes da Organization:** `features/ipm/organization/{receiver,manager,relay,conformance}` (hoje `{receiver,manager,publisher,reconciler,observer,executor,tests/e2e}`, decisão 0038); identidades `ipm-organization-receiver` e `ipm-organization-<papel>`; pacotes `ipm_organization_<papel>`; papéis de banco `ipm_organization_{manager,api,relay}` e `ipm_maintenance`; variáveis `IPM_ORGANIZATION_<PAPEL>_<SEÇÃO>_<CAMPO>`; consumer `ipm-organization-manager-requested`.
- **Contratos:** `schemas/ipm/organization/` e o índice `schemas/ipm.organization.index.json`.
- **Zitadel:** a organização de sistema `core` (usuários cadastrados, projeto `smarkee`) não muda. A service account do Executor da Organization passa a se chamar `ipm-organization-executor`, pela regra `<módulo>-<tipo>-<papel>`; em dev ela foi criada como `core-organization-executor` e foi renomeada na decisão 0038.
- **Prefixo das variáveis de ambiente por componente**, e não por módulo: `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>` (por exemplo, `IPM_ORGANIZATION_RECEIVER_NATS_URL`), para que os componentes de módulos e tipos diferentes não compartilhem nomes de variável nem arquivo `.env` ambíguo. Ajusta a regra de configuração da decisão 0015.

## Justificativa

- A dependência segue o sentido do domínio: a Organization depende do User, e não o contrário.
- A criação de uma Organization deixa de ser requisito para a plataforma existir; ela é uma funcionalidade do módulo de identidade, como a gestão de administradores e de usuários que virá depois.
- Fazer a mudança agora, durante o fatiamento em componentes (0015), custa só a renomeação, antes de qualquer release.

## Consequências

- Os módulos funcionais futuros (secrets, clusters) que isolam recursos por Organization passam a depender do módulo `ipm` para o `organizationId`. É o custo que a 0009 queria evitar, aceito porque a Organization é, de fato, parte da gestão de identidade.
- `docs/` (exemplos de subjects e de módulo), os agents, o `ROADMAP.md` e o `CHANGELOG.md` foram alinhados. O CLI usa a seção `[ipm]` e as variáveis `SK_IPM_*` (decisão 0008) para a Organization.
- Os objetos antigos `core.organization*` e os papéis `core_organization_*` e `core_relay` foram removidos do SSOT de dev (estavam vazios); o schema `core` segue com o User.
