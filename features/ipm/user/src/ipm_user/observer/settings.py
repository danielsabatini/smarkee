"""Configuração do Observer de User (decisões 0015 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_USER_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_USER_OBSERVER_MESSAGING_URL`
(`docs/data/SCHEMA.md` §8.3). Sem default: a senha do NATS e o ID do projeto de roles. O Observer
não acessa o SSOT e só **lê** o Zitadel (conta `ipm-user-observer`, `ORG_OWNER_VIEWER` em cada
organização de cliente, decisão 0077).
"""

from ipm_user.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_user.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Observer, com a conta de serviço `ipm-user-observer` (somente leitura)."""

    project_id: str | None = None
    """ID do projeto `roles-ipm`: as permissões do usuário são as autorizações nele. Sem default."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """`observationInterval` (PT5M) de `schemas/ipm/user/desired`."""

    observation_jitter: float = 0.2
    maximum_concurrent_reads: int = 4
    """Leituras simultâneas no Zitadel: limita a pressão sobre o provedor."""


class UserObserverSettings(RoleSettings):
    model_config = role_config("observer")

    messaging: StateMessagingSettings = StateMessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: UserObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_USER_OBSERVER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_PROJECT_ID": bool(settings.identity.project_id),
        },
    )
