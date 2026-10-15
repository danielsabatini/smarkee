"""Configuração do Manager de `sum.service` (decisões 0015, 0019 e 0033).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `SUM_SERVICE_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`SUM_SERVICE_MANAGER_NATS_URL`. As senhas e o catálogo não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str = "sum_service_manager_login"
    """Papel de login do Manager do tipo (`infrastructure/dev/database/bootstrap/sum.sql`)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class CatalogSettings(_Section):
    roles: str | None = None
    """Catálogo serviço → roles em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`.
    Sem default: o Manager não sobe sem um catálogo (decisão 0033)."""


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018)."""


class SumServiceManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_MANAGER_",
        # SUM_SERVICE_MANAGER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    catalog: CatalogSettings = CatalogSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = (
    "SUM_SERVICE_MANAGER_NATS_PASSWORD",
    "SUM_SERVICE_MANAGER_DATABASE_PASSWORD",
    "SUM_SERVICE_MANAGER_CATALOG_ROLES",
)


def missing_required(settings: SumServiceManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "SUM_SERVICE_MANAGER_NATS_PASSWORD": settings.nats.password is not None,
        "SUM_SERVICE_MANAGER_DATABASE_PASSWORD": settings.database.password is not None,
        "SUM_SERVICE_MANAGER_CATALOG_ROLES": bool(settings.catalog.roles),
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
