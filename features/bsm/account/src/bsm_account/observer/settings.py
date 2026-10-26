"""Configuração do Observer de Billing Account (decisões 0015 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `BSM_ACCOUNT_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo
`BSM_ACCOUNT_OBSERVER_MESSAGING_URL`
(`docs/data/SCHEMA.md` §8.3). Sem default: a senha do NATS. O Observer
não acessa o SSOT e só **lê** o armazenamento de estado do recurso.
"""

from bsm_account.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class StorageSettings(Section):
    directory: str | None = None
    """Diretório dos arquivos de estado da Billing Account (somente leitura no Observer)."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """`observationInterval` (PT5M) de `schemas/bsm/account/desired`."""

    observation_jitter: float = 0.2
    maximum_concurrent_reads: int = 4
    """Leituras simultâneas no armazenamento de estado."""


class AccountObserverSettings(RoleSettings):
    model_config = role_config("observer")

    messaging: StateMessagingSettings = StateMessagingSettings()
    storage: StorageSettings = StorageSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: AccountObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "BSM_ACCOUNT_OBSERVER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "STORAGE_DIRECTORY": bool(settings.storage.directory),
        },
    )
