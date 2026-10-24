"""Configuração do Executor de User (decisões 0015, 0063 e 0077).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_USER_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_USER_EXECUTOR_MESSAGING_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS e o ID do projeto de roles. O Executor
**não acessa o SSOT** e escreve no Zitadel só o usuário, as autorizações dele e o metadado.
"""

from ipm_user.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_user.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Executor: conta `ipm-user-executor`.

    Papéis dela, dados pelo operador em cada organização de cliente (decisão 0077):
    `ORG_USER_CREATOR` na organização (cria e remove usuários) e `PROJECT_GRANT_OWNER` no Project
    Grant de `roles-ipm` para ela (concede as roles do Grant, e nenhuma outra).
    """

    project_id: str | None = None
    """ID do projeto `roles-ipm`: o único em que o Executor concede permissões. Sem default."""

    timeout_seconds: float = 10.0


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class UserExecutorSettings(RoleSettings):
    model_config = role_config("executor")

    messaging: MessagingSettings = MessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: UserExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_USER_EXECUTOR_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_PROJECT_ID": bool(settings.identity.project_id),
        },
    )
