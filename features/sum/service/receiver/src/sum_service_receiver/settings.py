"""Configuração do Receiver de `sum.service` (decisões 0015 e 0033).

Ordem: variável de ambiente → default. Nome: `SUM_SERVICE_RECEIVER_<SEÇÃO>_<CAMPO>`. As senhas e a
audience não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str = "sum_service_receiver_login"
    """Papel de login do Receiver: só `SELECT` nas views de `sum.service` (decisão 0033)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class AuthSettings(_Section):
    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    """Valor esperado de `iss`: o endereço público do provedor de identidade."""

    jwks_url: str = "http://gateway.smarkee.internal:8000/oauth/v2/keys"
    host_header: str = "ipm-dev.smarkee.com.br:8080"
    audience: str | None = None
    """ID do projeto de roles do SUM (`roles-sum`): audience dos tokens aceitos."""

    jwks_cache_seconds: int = 300


class ApiSettings(_Section):
    host: str = "0.0.0.0"  # noqa: S104 (escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000
    client_address_header: str | None = "x-forwarded-for"


class SumServiceReceiverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_RECEIVER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()


REQUIRED_SECRETS = (
    "SUM_SERVICE_RECEIVER_AUTH_AUDIENCE",
    "SUM_SERVICE_RECEIVER_NATS_PASSWORD",
    "SUM_SERVICE_RECEIVER_DATABASE_PASSWORD",
)


def missing_required(settings: SumServiceReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "SUM_SERVICE_RECEIVER_AUTH_AUDIENCE": bool(settings.auth.audience),
        "SUM_SERVICE_RECEIVER_NATS_PASSWORD": settings.nats.password is not None,
        "SUM_SERVICE_RECEIVER_DATABASE_PASSWORD": settings.database.password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
