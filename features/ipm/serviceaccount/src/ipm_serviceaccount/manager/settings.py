"""Configuração do Manager de Service Account (decisões 0015, 0019 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `IPM_SERVICEACCOUNT_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_SERVICEACCOUNT_MANAGER_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas não têm default.
"""

from ipm_serviceaccount.common.settings import (
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
    """Falhas por geração antes de `Failed` (`schemas/ipm/serviceaccount/desired`, `failureLimit`)."""

    progress_deadline_seconds: int = 300
    """Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded`
    (`schemas/ipm/serviceaccount/desired`, `progressDeadline`; decisão 0078)."""


class ServiceaccountManagerSettings(RoleSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: ServiceaccountManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_SERVICEACCOUNT_MANAGER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
