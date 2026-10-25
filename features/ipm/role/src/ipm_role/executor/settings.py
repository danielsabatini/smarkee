"""Configuração do Executor de Role (decisões 0015, 0063 e 0083).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_ROLE_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ROLE_EXECUTOR_MESSAGING_URL`
(`docs/SCHEMA.md` §8.3). Sem default: as senhas do banco e do NATS. O Executor
**não acessa o SSOT** e é o único componente com escrita no estado do recurso, no banco `platform`.
"""

from ipm_role.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class RoleExecutorSettings(RoleSettings):
    model_config = role_config("executor")

    database: DatabaseSettings = DatabaseSettings()
    """Banco `platform` (plano de dados), e não o SSOT (decisão 0086)."""

    messaging: MessagingSettings = MessagingSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: RoleExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ROLE_EXECUTOR_",
        {
            "DATABASE_PASSWORD": settings.database.password is not None,
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
