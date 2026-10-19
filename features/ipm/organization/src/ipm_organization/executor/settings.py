"""Configuração do Executor de Organization (decisões 0015 e 0063).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_EXECUTOR_MESSAGING_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS. O Executor
**não acessa o SSOT** e escreve só a organização no Zitadel.
"""

from pydantic_settings import BaseSettings

from ipm_organization.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_organization.common.settings import (
    HealthSettings,
    MessagingSettings,
    Section,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Executor: conta `ipm-organization-executor` (`IAM_ORG_MANAGER`, de instância)."""

    timeout_seconds: float = 10.0


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class OrganizationExecutorSettings(BaseSettings):
    model_config = role_config("executor")

    messaging: MessagingSettings = MessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: OrganizationExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_EXECUTOR_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
