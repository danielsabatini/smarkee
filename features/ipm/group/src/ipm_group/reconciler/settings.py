"""Configuração do Reconciler de Grupo (decisões 0015, 0063, 0086 e 0088).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_GROUP_RECONCILER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_GROUP_RECONCILER_MESSAGING_URL`
(`docs/data/SCHEMA.md` §8.3). A senha do NATS não tem default. O Reconciler não acessa o SSOT.
"""

from ipm_group.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class LoopSettings(Section):
    """Parâmetros do loop do tipo (`x-resourceParameters` de `schemas/ipm/group/desired`)."""

    observation_validity_seconds: int = 600
    """`observationValidity` (PT10M): idade máxima de um `observed` para decidir."""

    action_deadline_seconds: int = 120
    """`actionDeadline` (PT2M): prazo da `action` pendente e da espera pela observação causada."""

    reevaluation_interval_seconds: int = 30
    """Período da reavaliação periódica de todos os recursos (com jitter)."""

    reevaluation_jitter: float = 0.2
    failure_backoff_seconds: int = 5
    """Atraso após o primeiro `failed`; dobra a cada falha seguida, até o máximo."""

    failure_backoff_maximum_seconds: int = 300


class GroupReconcilerSettings(RoleSettings):
    model_config = role_config("reconciler")

    messaging: StateMessagingSettings = StateMessagingSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: GroupReconcilerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_GROUP_RECONCILER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
