"""Configuração do relay de Organization (decisão 0015).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_RELAY_<SEÇÃO>_<CAMPO>`, por exemplo `IPM_ORGANIZATION_RELAY_NATS_URL`
(`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str = "ipm_organization_relay_login"
    """Papel de login do relay: lê o outbox e marca `published_at` (`docs/POSTGRESQL.md` §14.2)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class OrganizationRelaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_RELAY_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()


REQUIRED_SECRETS = (
    "IPM_ORGANIZATION_RELAY_NATS_PASSWORD",
    "IPM_ORGANIZATION_RELAY_DATABASE_PASSWORD",
)


def missing_required(settings: OrganizationRelaySettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "IPM_ORGANIZATION_RELAY_NATS_PASSWORD": settings.nats.password is not None,
        "IPM_ORGANIZATION_RELAY_DATABASE_PASSWORD": settings.database.password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
