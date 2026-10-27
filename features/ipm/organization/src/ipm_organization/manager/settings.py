"""Configuração do Manager de Organization (decisões 0015, 0019 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `IPM_ORGANIZATION_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_MANAGER_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas não têm default.
"""

from ipm_organization.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class LoopSettings(Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` (`schemas/ipm/organization/desired`, `failureLimit`)."""

    progress_deadline_seconds: int = 300
    """Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded`
    (`schemas/ipm/organization/desired`, `progressDeadline`; decisão 0078)."""


class UserAccessSettings(Section):
    """Contas do `ipm/user` que recebem permissões em cada Organization (decisão 0081).

    São IDs do provedor de identidade, que mudam por ambiente; o catálogo do Grant não é
    configuração: vem do contrato (`grantablePermission`). Sem default.
    """

    user_executor_account_id: str | None = None
    """Conta `ipm-user-executor` (organização `core`)."""

    user_observer_account_id: str | None = None
    """Conta `ipm-user-observer` (organização `core`)."""

    serviceaccount_executor_account_id: str | None = None
    """Conta `ipm-serviceaccount-executor` (organização `core`; decisão 0094)."""

    serviceaccount_observer_account_id: str | None = None
    """Conta `ipm-serviceaccount-observer` (organização `core`; decisão 0094)."""

    serviceaccount_controller_account_id: str | None = None
    """Conta `ipm-serviceaccount-controller` (organização `core`; decisão 0096)."""

    user_controller_account_id: str | None = None
    """Conta `ipm-user-controller` (organização `core`; decisão 0096)."""


class OrganizationManagerSettings(RoleSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    loop: LoopSettings = LoopSettings()
    user_access: UserAccessSettings = UserAccessSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: OrganizationManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_MANAGER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "USER_ACCESS_USER_EXECUTOR_ACCOUNT_ID": bool(
                settings.user_access.user_executor_account_id
            ),
            "USER_ACCESS_USER_OBSERVER_ACCOUNT_ID": bool(
                settings.user_access.user_observer_account_id
            ),
            "USER_ACCESS_SERVICEACCOUNT_EXECUTOR_ACCOUNT_ID": bool(
                settings.user_access.serviceaccount_executor_account_id
            ),
            "USER_ACCESS_SERVICEACCOUNT_OBSERVER_ACCOUNT_ID": bool(
                settings.user_access.serviceaccount_observer_account_id
            ),
            "USER_ACCESS_SERVICEACCOUNT_CONTROLLER_ACCOUNT_ID": bool(
                settings.user_access.serviceaccount_controller_account_id
            ),
            "USER_ACCESS_USER_CONTROLLER_ACCOUNT_ID": bool(
                settings.user_access.user_controller_account_id
            ),
        },
    )
