# 0076 — "Administrador" no lugar de "membro"

- **Data:** 2026-10-20
- **Status:** Aceita e aplicada à documentação, às decisões e à suíte de conformidade de identidade. Revisa o termo das decisões 0039 §5 e 0042.
- **Origem:** pedido do responsável pelo projeto: onde "membro" significa quem administra a Organization, passa a ser "administrador", em todos os lugares.

## Contexto

O projeto usava "membro" para o acesso de uma pessoa a uma Organization (decisão 0039 §5: "o dono é o primeiro membro, com o papel de administrador") e reservava `member` para esse vínculo (decisão 0042). No Zitadel, porém, "membro" tem outro sentido: era o nome antigo do **administrador**, quem recebe papéis nativos de administração de uma instância, organização ou projeto (`ORG_OWNER`, `ORG_USER_MANAGER`, `ORG_OWNER_VIEWER`...). Na API v2 isso é o `InternalPermissionService` (`ListAdministrators`), e o console mostra "Add an Administrator". O Zitadel não tem um "membro" de negócio. Dois sentidos para a mesma palavra confundiam o desenho.

## Decisão

- **"Membro" deixa de ser usado** para o acesso a uma Organization. Quem administra a Organization é o **administrador**, no mesmo sentido do Zitadel: uma pessoa com papéis nativos de administração na organização.
- **Onde "membro" falava de forma geral das pessoas com acesso à Organization** (por exemplo, "futuros membros", "gestão de membros"), o texto passa a "administradores e usuários".
- **Continuam como estão**, porque são outra coisa:
  - identificadores do próprio Zitadel, como as permissões `org.member.read`, `project.member.write`, `user.membership.read` e a mensagem `membership not found` (AGENTS §15.1);
  - outros sentidos de "membro": papel de função do PostgreSQL, grupo de consumers do NATS, cluster do etcd, membros de estruturas de código.
- **Na decisão 0042**, `member` dá lugar a `administrator` na regra "um nome por conceito".

## O que mudou

- Decisões 0009, 0010, 0014, 0016, 0029, 0038, 0039 §5, 0042 e 0043; `docs/loop/RESOURCE-CONTROL-LOOP.md`; o README de `ipm/organization`; o `CHANGELOG.md`; o `MEMORY.md`.
- Conformidade de identidade: a tabela do README ("Administradores da instância") e o teste (`organization_administrators`, `test_instance_administrators`).

## Consequências

- Nenhum contrato, rota, role ou dado mudou: o termo ainda não tinha virado código de produto.
- O acesso de negócio à Organization foi decidido na 0077: a conta dona é o root, e as demais pessoas são usuários da Organization (`ipm.user`) com roles da plataforma. Não haverá administrador de negócio separado; "administrador" fica como o termo do Zitadel para papéis nativos de administração.
