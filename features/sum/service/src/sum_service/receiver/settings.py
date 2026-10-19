"""Configuração do Receiver de `sum.service` (decisões 0015 e 0033).

Ordem: variável de ambiente → default. Nome: `SUM_SERVICE_RECEIVER_<SEÇÃO>_<CAMPO>`. As senhas e a
audience não têm default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from sum_service.common.settings import DatabaseSettings as CommonDatabaseSettings
from sum_service.common.settings import (
    NatsSettings,
    Section,
    missing_variables,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "sum_service_receiver_login"
    """Papel de login do Receiver: só `SELECT` nas views de `sum.service` (decisão 0033)."""


class AuthSettings(Section):
    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    """Valor esperado de `iss`: o endereço público do provedor de identidade."""

    jwks_url: str = "http://gateway.smarkee.internal:8000/oauth/v2/keys"
    host_header: str = "ipm-dev.smarkee.com.br:8080"
    audience: str | None = None
    """ID do projeto de roles do SUM (`roles-sum`): audience dos tokens aceitos."""

    jwks_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000


class PeersSettings(Section):
    """Receivers dos outros módulos, na rede interna, consultados ao desabilitar um serviço."""

    organizations_url: str = "http://ipm-organization-receiver.smarkee.internal:8000"
    timeout_seconds: float = 5.0


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
    peers: PeersSettings = PeersSettings()


def missing_required(settings: SumServiceReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_RECEIVER_",
        {
            "AUTH_AUDIENCE": bool(settings.auth.audience),
            "NATS_PASSWORD": settings.nats.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
