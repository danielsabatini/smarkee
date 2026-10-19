"""Configuração do Manager de Account (decisões 0015, 0019 e 0063).

Ordem: variável de ambiente → default (seções comuns em `common/settings.py`).

Nome da variável: `CORE_ACCOUNT_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_MANAGER_NATS_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from core_account.common.settings import DatabaseSettings as CommonDatabaseSettings
from core_account.common.settings import (
    HealthSettings,
    NatsSettings,
    Section,
    missing_variables,
)
from core_account.manager.domain.account import DEFAULT_PLATFORM_ROLES


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "core_account_manager_login"
    """Papel de login do Manager do tipo (`docs/POSTGRESQL.md` §14.2)."""


class LoopSettings(Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` (`schemas/core/account/desired`, `failureLimit`)."""


class PlatformSettings(Section):
    roles: tuple[str, ...] = DEFAULT_PLATFORM_ROLES
    """Roles de ação gravadas no `desired` do usuário cadastrado (decisão 0025). Lista em JSON."""


class AccountManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_ACCOUNT_MANAGER_",
        # CORE_ACCOUNT_MANAGER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    loop: LoopSettings = LoopSettings()
    platform: PlatformSettings = PlatformSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: AccountManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_MANAGER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
