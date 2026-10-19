"""Configuração do Executor de Account (decisões 0015 e 0063).

Ordem: variável de ambiente → default. Nome da variável:
`CORE_ACCOUNT_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo `CORE_ACCOUNT_EXECUTOR_NATS_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS e os identificadores do Zitadel. O Executor
**não acessa o SSOT** e é a única identidade com escrita no Zitadel.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core_account.common.identity import IdentitySettings as CommonIdentitySettings
from core_account.common.settings import (
    HealthSettings,
    MessagingSettings,
    Section,
    missing_variables,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Executor, com a conta de serviço `core-account-executor`.

    Papéis dela: `ORG_USER_CREATOR` na `register` (cria e remove usuários, sem conceder roles) e
    `PROJECT_GRANT_OWNER` nos Project Grants dos projetos de `project_ids` (decisão 0032).
    """

    register_organization_id: str | None = None
    """ID da organização `register`: onde os usuários são criados e recebem as autorizações.
    Sem default."""

    project_ids: dict[str, str] = Field(default_factory=dict)
    """IDs dos projetos de roles que o Executor pode conceder, por módulo (`{"core": "<ID>", ...}`).

    A role `<módulo>.<tipo>.<ação>` vai para o projeto do seu módulo. Um módulo ausente aqui é
    rejeitado antes de chamar o Zitadel; o Zitadel também nega o que o Executor não tem como
    `PROJECT_GRANT_OWNER` (decisão 0032). Sem default.
    """

    timeout_seconds: float = 10.0


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class AccountExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_ACCOUNT_EXECUTOR_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: MessagingSettings = MessagingSettings()
    zitadel: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: AccountExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_EXECUTOR_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "ZITADEL_REGISTER_ORGANIZATION_ID": bool(settings.zitadel.register_organization_id),
            "ZITADEL_PROJECT_IDS": bool(settings.zitadel.project_ids),
        },
    )
