"""Configuração do Controller de service account (decisão 0096).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_SERVICEACCOUNT_CONTROLLER_<SEÇÃO>_<CAMPO>`.
"""

from ipm_serviceaccount.common.database import DatabaseSettings
from ipm_serviceaccount.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_serviceaccount.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Controller: conta `ipm-serviceaccount-controller`, que lê e escreve as máquinas.

    Papéis dela, dados pelo operador em cada organização de cliente (decisão 0077):
    `ORG_USER_CREATOR` (cria e remove usuários), `ORG_OWNER_VIEWER` (lê) e `PROJECT_GRANT_OWNER` no
    Project Grant de `roles-ipm` para ela (concede as roles do Grant, e nenhuma outra).
    """

    timeout_seconds: float = 10.0
    project_id: str | None = None
    """ID do projeto `roles-ipm`: o único em que o Controller concede permissões. Sem default."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância reconcilia só `hash mod count == index`."""


class LoopSettings(Section):
    reevaluation_interval_seconds: int = 300
    """Intervalo periódico de reavaliação de todos os recursos gerenciados."""

    reevaluation_jitter: float = 0.2
    workers: int = 2
    """Número de workers simultâneos de reconciliação."""

    failure_limit: int = 5
    """Falhas de ação até suspender a reconciliação (`SSOT.md` §10.3)."""

    progress_deadline_seconds: int = 300
    """Prazo de progresso para a geração convergir antes de marcar Failed."""


class ServiceAccountControllerSettings(RoleSettings):
    model_config = role_config("controller")

    database: DatabaseSettings = DatabaseSettings()
    messaging: StateMessagingSettings = StateMessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: ServiceAccountControllerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_SERVICEACCOUNT_CONTROLLER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "IDENTITY_PROJECT_ID": bool(settings.identity.project_id),
        },
    )
