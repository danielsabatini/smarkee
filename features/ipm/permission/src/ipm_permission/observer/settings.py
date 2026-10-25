"""Configuração do Observer de Permission (decisões 0015, 0063 e 0083).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_PERMISSION_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_PERMISSION_OBSERVER_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS. O
Observer não acessa o SSOT e só **lê** o Zitadel (conta `ipm-permission-observer`, somente leitura
nos projetos `roles-<módulo>`).
"""

from ipm_permission.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_permission.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Configuração de acesso somente leitura ao Zitadel para `ipm-permission-observer`."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa `hash(resourceId) mod count == index`."""


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """`observationInterval` de `schemas/ipm/permission/desired.v1.schema.json` (PT5M = 300 s)."""

    observation_jitter: float = 0.2
    """Fração de jitter (±20%) aplicada ao intervalo periódico (`docs/RESOURCE-CONTROL-LOOP.md`)."""

    maximum_concurrent_reads: int = 10
    """Limite de leituras simultâneas ao Zitadel por instância, na observação periódica."""


class PermissionObserverSettings(RoleSettings):
    model_config = role_config("observer")

    messaging: StateMessagingSettings = StateMessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: PermissionObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_PERMISSION_OBSERVER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
