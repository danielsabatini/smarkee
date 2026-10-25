"""Configuração do Manager de Permission (decisões 0015, 0019, 0063 e 0083).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `IPM_PERMISSION_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_PERMISSION_MANAGER_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from ipm_permission.common.settings import (
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
    """Falhas por geração antes de `Failed` (`schemas/ipm/permission/desired`, `failureLimit`)."""

    progress_deadline_seconds: int = 300
    """Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded`
    (`schemas/ipm/permission/desired`, `progressDeadline`; decisão 0078)."""


class PermissionManagerSettings(RoleSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: PermissionManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_PERMISSION_MANAGER_",
        {
            "DATABASE_PASSWORD": settings.database.password is not None,
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
