"""Configuração do Receiver de User (decisão 0015).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `CORE_USER_RECEIVER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_USER_RECEIVER_NATS_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str = "core_user_receiver_login"
    """Papel de login do Receiver: só `SELECT` nas views do tipo (`docs/POSTGRESQL.md` §14.2)."""

    password: SecretStr | None = None


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class AuthSettings(_Section):
    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    """Valor esperado de `iss`: o endereço público do provedor de identidade."""

    jwks_url: str = "http://gateway.smarkee.internal:8000/oauth/v2/keys"
    """Endereço (da rede interna) em que as chaves públicas são buscadas."""

    userinfo_url: str = "http://gateway.smarkee.internal:8000/oidc/v1/userinfo"

    host_header: str = "ipm-dev.smarkee.com.br:8080"
    """`Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor."""

    audience: str | None = None
    """ID do projeto da plataforma (audience dos access tokens). Sem default."""

    jwks_cache_seconds: int = 300
    userinfo_cache_seconds: int = 300


class ApiSettings(_Section):
    host: str = "0.0.0.0"  # noqa: S104 (o componente escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000
    anonymous_rate_limit: int = 5
    anonymous_rate_window_seconds: int = 60
    client_address_header: str | None = "x-forwarded-for"
    """Cabeçalho com o endereço do cliente, definido pelo gateway (único acesso ao serviço)."""


class UserReceiverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_USER_RECEIVER_",
        # CORE_USER_RECEIVER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()


REQUIRED_SECRETS = (
    "CORE_USER_RECEIVER_AUTH_AUDIENCE",
    "CORE_USER_RECEIVER_NATS_PASSWORD",
    "CORE_USER_RECEIVER_DATABASE_PASSWORD",
)


def missing_required(settings: UserReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "CORE_USER_RECEIVER_AUTH_AUDIENCE": bool(settings.auth.audience),
        "CORE_USER_RECEIVER_NATS_PASSWORD": settings.nats.password is not None,
        "CORE_USER_RECEIVER_DATABASE_PASSWORD": settings.database.password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
