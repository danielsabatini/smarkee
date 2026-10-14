# 0026 — Projeto `roles` na organização `core` e organização `register`

- **Data:** 2026-10-14
- **Status:** Aceita

## Contexto

No Zitadel de dev, a organização `core` tinha o projeto `smarkee`, com o mesmo nome da organização dos operadores e do banco. O nome não dizia o que o projeto guarda. Além disso, a organização `core` reúne hoje o projeto das roles e os usuários cadastrados, duas responsabilidades que a próxima fase vai separar.

## Decisão

- **`core` → `roles`:** a organização `core` é dona do projeto **`roles`** (antes `smarkee`), que contém as roles da plataforma e a aplicação `cli`. A leitura passa a ser "organização `core`, projeto `roles`".
- **`register`:** nova organização **`register`**, destinada aos usuários cadastrados. Um projeto `users` foi criado junto, vazio, e removido pela decisão 0027 por não ter função.
- **Escopo desta decisão:** só nomes e a criação das estruturas. Os usuários, o cadastro e as service accounts dos Executors **continuam na organização `core`**; mover tudo para a `register` é a fase seguinte.

## Justificativa

- Nomes que dizem o que contêm reduzem erro de configuração (`organization_id`, `project_id`) e preparam a separação entre quem define as roles e quem as recebe.
- Renomear um projeto no Zitadel não muda o ID. Audience dos tokens, claim de roles (`urn:zitadel:iam:org:project:<ID>:roles`), `CORE_ZITADEL_PROJECT_ID` e `*_AUTH_AUDIENCE` seguem iguais.

## Consequências

- Aplicado no Zitadel de dev em 2026-10-14, pela API de gestão com a conta de bootstrap (script temporário, não versionado): projeto `394490764261851138` renomeado; organização `register` e projeto `users` criados. O teste e2e do loop completo passou depois da mudança.
- Documentação atualizada (`infrastructure/dev/README.md`, README e `.env.example` do User, README do Executor e docstrings). As decisões 0010, 0014 e 0016 mantêm o nome `smarkee` do projeto como foi escrito na época; vale a leitura "projeto `roles`".
- O projeto `smarkee` antigo da organização `smarkee` (5 roles, aplicação `cli` sem JWT) não foi tocado.
- Stg e prd (Kubernetes) devem seguir os mesmos nomes quando forem criados.
