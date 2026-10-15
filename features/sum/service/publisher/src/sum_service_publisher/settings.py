"""Configuração do Publisher de `sum.service` (decisões 0015 e 0019).

Ordem: variável de ambiente → default. Nome da variável: `SUM_SERVICE_PUBLISHER_<SEÇÃO>_<CAMPO>`,
por exemplo `SUM_SERVICE_PUBLISHER_NATS_URL`. As senhas não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str = "sum_service_publisher_login"
    """Papel de login do Publisher (lê o outbox e marca `published_at`)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/*` (decisão 0018)."""


class SumServicePublisherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_PUBLISHER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = (
    "SUM_SERVICE_PUBLISHER_NATS_PASSWORD",
    "SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD",
)


def missing_required(settings: SumServicePublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "SUM_SERVICE_PUBLISHER_NATS_PASSWORD": settings.nats.password is not None,
        "SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD": settings.database.password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
