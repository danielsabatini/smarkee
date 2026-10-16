"""Configuração do Manager de Organization (decisões 0015 e 0019).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `IPM_ORGANIZATION_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_MANAGER_NATS_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str = "ipm_organization_manager_login"
    """Papel de login do Manager do tipo (`docs/POSTGRESQL.md` §14.2)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class LoopSettings(_Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` (`schemas/ipm/organization/desired`, `failureLimit`)."""


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018)."""


class OrganizationManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_MANAGER_",
        # IPM_ORGANIZATION_MANAGER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = (
    "IPM_ORGANIZATION_MANAGER_NATS_PASSWORD",
    "IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD",
)


def missing_required(settings: OrganizationManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "IPM_ORGANIZATION_MANAGER_NATS_PASSWORD": settings.nats.password is not None,
        "IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD": settings.database.password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
