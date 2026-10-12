"""Configuração do Publisher de User (decisões 0015 e 0019).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `CORE_USER_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo `CORE_USER_PUBLISHER_NATS_URL`
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
    user: str = "core_user_publisher_login"
    """Papel de login do Publisher: lê o outbox e marca `published_at` (`POSTGRESQL.md` §14.2)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018)."""


class UserPublisherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_USER_PUBLISHER_",
        # CORE_USER_PUBLISHER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = (
    "CORE_USER_PUBLISHER_NATS_PASSWORD",
    "CORE_USER_PUBLISHER_DATABASE_PASSWORD",
)


def missing_required(settings: UserPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "CORE_USER_PUBLISHER_NATS_PASSWORD": settings.nats.password is not None,
        "CORE_USER_PUBLISHER_DATABASE_PASSWORD": settings.database.password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
