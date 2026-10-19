"""Configuração do Receiver de Account (decisão 0015).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `CORE_ACCOUNT_RECEIVER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_RECEIVER_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic_settings import BaseSettings

from core_account.common.settings import DatabaseSettings as CommonDatabaseSettings
from core_account.common.settings import MessagingSettings, Section, missing_variables, role_config


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "core_account_receiver_login"
    """Papel de login do Receiver: só `SELECT` nas views do tipo (`docs/POSTGRESQL.md` §14.2)."""


class AuthSettings(Section):
    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    """Valor esperado de `iss`: o endereço público do provedor de identidade."""

    jwks_url: str = "http://gateway.smarkee.internal:8000/oauth/v2/keys"
    """Endereço (da rede interna) em que as chaves públicas são buscadas."""

    host_header: str = "ipm-dev.smarkee.com.br:8080"
    """`Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor."""

    audience: str | None = None
    """ID do projeto da plataforma (audience dos access tokens). Sem default."""

    jwks_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (o componente escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000
    anonymous_rate_limit: int = 5
    anonymous_rate_window_seconds: int = 60
    client_address_header: str | None = "x-forwarded-for"
    """Cabeçalho com o endereço do cliente, definido pelo gateway (único acesso ao serviço)."""


class PeersSettings(Section):
    """Receivers dos outros módulos, na rede interna, consultados na exclusão da conta."""

    organizations_url: str = "http://ipm-organization-receiver.smarkee.internal:8000"
    services_url: str = "http://sum-service-receiver.smarkee.internal:8000"
    timeout_seconds: float = 5.0


class AccountReceiverSettings(BaseSettings):
    model_config = role_config("receiver")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    peers: PeersSettings = PeersSettings()


def missing_required(settings: AccountReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_RECEIVER_",
        {
            "AUTH_AUDIENCE": bool(settings.auth.audience),
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
