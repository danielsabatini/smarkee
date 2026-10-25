"""Configuração do Executor de Permission (decisões 0015, 0063 e 0083).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_PERMISSION_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_PERMISSION_EXECUTOR_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS. O
Executor não acessa o SSOT: só lê o NATS e escreve no Zitadel (`roles-<módulo>`, conta
`ipm-permission-executor`).
"""

from ipm_permission.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_permission.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Configuração de acesso de escrita ao Zitadel para `ipm-permission-executor`."""


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (`bootstrap/action.json`, decisão 0018)."""


class PermissionExecutorSettings(RoleSettings):
    model_config = role_config("executor")

    messaging: MessagingSettings = MessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: PermissionExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_PERMISSION_EXECUTOR_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
