"""Configuração do Observer de Grupo (decisões 0015, 0063, 0086 e 0088).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_GROUP_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_GROUP_OBSERVER_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3).
Sem default: as senhas do banco e do NATS. O Observer **não acessa o SSOT**;
só lê o banco `platform`.
"""

from ipm_group.common.settings import (
    DatabaseSettings,
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """`observationInterval` (PT5M) de `schemas/ipm/group/desired`."""

    observation_jitter: float = 0.2
    maximum_concurrent_reads: int = 4
    """Leituras simultâneas no banco `platform`."""


class GroupObserverSettings(RoleSettings):
    model_config = role_config("observer")

    database: DatabaseSettings = DatabaseSettings()
    """Banco `platform` (plano de dados), somente leitura, e não o SSOT (decisão 0086)."""

    messaging: StateMessagingSettings = StateMessagingSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: GroupObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_GROUP_OBSERVER_",
        {
            "DATABASE_PASSWORD": settings.database.password is not None,
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
