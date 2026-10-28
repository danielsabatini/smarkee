"""Configuração do Controller de `sum.service` (decisões 0015, 0032, 0033 e 0096).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `SUM_SERVICE_CONTROLLER_<SEÇÃO>_<CAMPO>`. Sem default: senhas, identificadores
do Zitadel e o catálogo.
"""

from pydantic import Field

from sum_service.common.identity import IdentitySettings as CommonIdentitySettings
from sum_service.common.settings import (
    DatabaseSettings,
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Controller, com a conta de serviço `sum-service-controller`.

    Papéis dela: `ORG_OWNER_VIEWER` na organização `register` (lê usuários e autorizações) e
    `PROJECT_GRANT_OWNER` nos Project Grants dos projetos de `project_ids` (concede as roles do
    Grant, e nenhuma outra; decisão 0032).
    """

    register_organization_id: str | None = None
    """ID da organização `register`: onde os usuários recebem as autorizações. Sem default."""

    project_ids: dict[str, str] = Field(default_factory=dict)
    """IDs dos projetos de permissões que o Controller pode conceder, por módulo
    (`{"ipm": "<ID>", ...}`).

    A permissão `<módulo>.<tipo>.<ação>` vai para o projeto do seu módulo. Um módulo ausente aqui é
    rejeitado antes de chamar o Zitadel; o Zitadel também nega o que o Controller não tem como
    `PROJECT_GRANT_OWNER` (decisão 0032). Sem default.
    """

    timeout_seconds: float = 10.0


class CatalogSettings(Section):
    permissions: str | None = None
    """Catálogo serviço → permissões em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`.
    Sem default: o Controller não sobe sem um catálogo (decisão 0033)."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância reconcilia só `hash mod count == index`."""


class LoopSettings(Section):
    reevaluation_interval_seconds: int = 300
    """Intervalo periódico de reavaliação de todos os recursos gerenciados."""

    reevaluation_jitter: float = 0.2
    workers: int = 2
    """Número de workers simultâneos de reconciliação."""

    failure_limit: int = 5
    """Falhas de ação até suspender a reconciliação (`SSOT.md` §10.3)."""

    progress_deadline_seconds: int = 300
    """Prazo de progresso para a geração convergir antes de marcar Failed."""


class SumServiceControllerSettings(RoleSettings):
    model_config = role_config("controller")

    database: DatabaseSettings = DatabaseSettings()
    messaging: StateMessagingSettings = StateMessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()
    catalog: CatalogSettings = CatalogSettings()


def missing_required(settings: SumServiceControllerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_CONTROLLER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "IDENTITY_REGISTER_ORGANIZATION_ID": bool(settings.identity.register_organization_id),
            "IDENTITY_PROJECT_IDS": bool(settings.identity.project_ids),
            "CATALOG_PERMISSIONS": bool(settings.catalog.permissions),
        },
    )
