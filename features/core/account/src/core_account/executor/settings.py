"""Configuração do Executor de Account (decisões 0015 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `CORE_ACCOUNT_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_EXECUTOR_MESSAGING_URL`
(`docs/data/SCHEMA.md` §8.3). Sem default: a senha do NATS e os identificadores do Zitadel. O
Executor
**não acessa o SSOT** e é a única identidade com escrita no Zitadel.
"""

from pydantic import Field

from core_account.common.identity import IdentitySettings as CommonIdentitySettings
from core_account.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Executor, com a conta de serviço `core-account-executor`.

    Papéis dela: `ORG_USER_CREATOR` na `register` (cria e remove usuários, sem conceder
    permissões) e `PROJECT_GRANT_OWNER` nos Project Grants dos projetos de `project_ids` (decisão
    0032).
    """

    register_organization_id: str | None = None
    """ID da organização `register`: onde os usuários são criados e recebem as autorizações.
    Sem default."""

    project_ids: dict[str, str] = Field(default_factory=dict)
    """IDs dos projetos de permissões que o Executor pode conceder, por módulo
    (`{"core": "<ID>", ...}`).

    A permissão `<módulo>.<tipo>.<ação>` vai para o projeto do seu módulo. Um módulo ausente aqui é
    rejeitado antes de chamar o Zitadel; o Zitadel também nega o que o Executor não tem como
    `PROJECT_GRANT_OWNER` (decisão 0032). Sem default.
    """

    timeout_seconds: float = 10.0


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class AccountExecutorSettings(RoleSettings):
    model_config = role_config("executor")

    messaging: MessagingSettings = MessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: AccountExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_EXECUTOR_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_REGISTER_ORGANIZATION_ID": bool(settings.identity.register_organization_id),
            "IDENTITY_PROJECT_IDS": bool(settings.identity.project_ids),
        },
    )
