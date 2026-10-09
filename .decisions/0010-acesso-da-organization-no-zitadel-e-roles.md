# 0010 — Acesso da Organization no Zitadel e roles da plataforma

- **Data:** 2026-10-09
- **Status:** Aceita

## Contexto

Ao criar uma Organization, o primeiro usuário dela deve conseguir entrar na plataforma (`sk auth login`) sem passos manuais. Duas formas foram avaliadas:

1. um projeto e uma aplicação `cli` dentro de cada organização do Zitadel;
2. um único projeto da plataforma, delegado a cada organização.

## Decisão

- **Projeto único `smarkee`** na organização `smarkee` (a da plataforma), com:
  - todas as roles da plataforma;
  - uma aplicação nativa `cli` por ambiente (decisão 0007), usada por todas as Organizations.
- Na criação de uma Organization, o Executor aplica no Zitadel, nesta ordem e cada passo de forma idempotente:
  1. a organização, com `organization_id = resourceId` (decisão 0006);
  2. o **Project Grant** do projeto `smarkee` para a organização, com as roles delegáveis;
  3. o **primeiro usuário** administrador, com o grant da role `organization.admin`. O Zitadel envia o convite por e-mail.
- **Roles iniciais:**

  | Role | Delegável | Uso |
  |---|---|---|
  | `platform.admin` | Não | Operadores da plataforma (org `smarkee`): criam e gerenciam Organizations |
  | `organization.admin` | Sim | Administrador de uma Organization (primeiro usuário) |
  | `organization.viewer` | Sim | Leitura dentro de uma Organization |

- O `sk organization create --wait` devolve os parâmetros de login do primeiro usuário: `sk auth init --issuer … --client-id … --organization <organizationId>`. O comando não grava o `config.toml` de quem o executa, que é o operador, e não o usuário da Organization.

## Justificativa

- Um projeto por organização inverteria a delegação: cada organização seria dona das próprias roles, as roles seriam duplicadas e as APIs teriam de aceitar a audience de N projetos.
- O projeto único com Project Grant é o modelo de delegação B2B do Zitadel. As APIs validam uma audience fixa e um conjunto único de roles.

## Consequências

- O Executor precisa de uma credencial com permissão de instância no Zitadel (decisão 0011).
- O ID do projeto `smarkee` e as chaves das roles são configuração do serviço `core`.
- A remoção de uma Organization remove a organização no Zitadel, e com ela o grant e os usuários.
