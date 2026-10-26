"""Configuração do Observer de Account (decisões 0015 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `CORE_ACCOUNT_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_OBSERVER_MESSAGING_URL`
(`docs/data/SCHEMA.md` §8.3). Sem default: a senha do NATS e os identificadores do Zitadel. O
Observer
não acessa o SSOT e só **lê** o Zitadel (conta de serviço `core-account-observer`, somente leitura).
"""

from core_account.common.identity import IdentitySettings as CommonIdentitySettings
from core_account.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Observer, com a conta de serviço `core-account-observer` (somente leitura)."""

    register_organization_id: str | None = None
    """ID da organização `register`: onde estão os usuários e as autorizações deles. Sem default."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """`observationInterval` (PT5M) de `schemas/core/account/desired`."""

    observation_jitter: float = 0.2
    maximum_concurrent_reads: int = 4
    """Leituras simultâneas no Zitadel: limita a pressão sobre o provedor."""


class AccountObserverSettings(RoleSettings):
    model_config = role_config("observer")

    messaging: StateMessagingSettings = StateMessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: AccountObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_OBSERVER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_REGISTER_ORGANIZATION_ID": bool(settings.identity.register_organization_id),
        },
    )
