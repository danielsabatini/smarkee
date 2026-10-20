"""Configuração do Manager de Account (decisões 0015, 0019 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `CORE_ACCOUNT_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_MANAGER_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from core_account.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)
from core_account.manager.domain.account import DEFAULT_PLATFORM_ROLES


class LoopSettings(Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` (`schemas/core/account/desired`, `failureLimit`)."""


class PlatformSettings(Section):
    roles: tuple[str, ...] = DEFAULT_PLATFORM_ROLES
    """Roles de ação gravadas no `desired` do usuário cadastrado (decisão 0025). Lista em JSON."""


class AccountManagerSettings(RoleSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    loop: LoopSettings = LoopSettings()
    platform: PlatformSettings = PlatformSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: AccountManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_MANAGER_",
        {
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
