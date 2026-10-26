"""Configuração do Executor de Organization (decisões 0015 e 0063).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_ORGANIZATION_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_EXECUTOR_MESSAGING_URL`
(`docs/data/SCHEMA.md` §8.3). Sem default: a senha do NATS. O Executor
**não acessa o SSOT** e escreve no Zitadel só a organização e o preparo dela para os usuários
(decisão 0081).
"""

from ipm_organization.common.identity import IdentitySettings as CommonIdentitySettings
from ipm_organization.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Executor: conta `ipm-organization-executor` (`IAM_ORG_MANAGER`, de instância)."""

    timeout_seconds: float = 10.0
    project_id: str | None = None
    """ID do projeto `roles-ipm` (organização `core`): o do Project Grant de cada Organization
    (decisão 0081). Sem default."""


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class OrganizationExecutorSettings(RoleSettings):
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
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_PROJECT_ID": bool(settings.identity.project_id),
        },
    )
