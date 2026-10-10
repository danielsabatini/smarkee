"""Configuração do serviço `core` (decisão 0011).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o serviço roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `CORE_<SEÇÃO>_<CAMPO>`, por exemplo `CORE_NATS_URL` (`docs/SCHEMA.md` §8.3).
Cada papel do PostgreSQL tem o seu usuário e a sua senha (`docs/POSTGRESQL.md` §14.2); as
senhas não têm default.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_Section):
    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"

    organization_manager_user: str = "core_organization_manager_login"
    organization_manager_password: SecretStr | None = None
    organization_api_user: str = "core_organization_api_login"
    organization_api_password: SecretStr | None = None
    user_manager_user: str = "core_user_manager_login"
    user_manager_password: SecretStr | None = None
    user_api_user: str = "core_user_api_login"
    user_api_password: SecretStr | None = None
    relay_user: str = "core_relay_login"
    relay_password: SecretStr | None = None


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
    host: str = "0.0.0.0"  # noqa: S104 (o serviço escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000
    organization_quota: int = 1
    """Organizations por dono para quem não é operador (decisão 0010)."""

    anonymous_rate_limit: int = 5
    anonymous_rate_window_seconds: int = 60
    client_address_header: str | None = "x-forwarded-for"
    """Cabeçalho com o endereço do cliente, definido pelo gateway (único acesso ao serviço)."""


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_",
        # CORE_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()


REQUIRED_SECRETS = (
    "CORE_AUTH_AUDIENCE",
    "CORE_NATS_PASSWORD",
    "CORE_DATABASE_ORGANIZATION_MANAGER_PASSWORD",
    "CORE_DATABASE_ORGANIZATION_API_PASSWORD",
    "CORE_DATABASE_USER_MANAGER_PASSWORD",
    "CORE_DATABASE_USER_API_PASSWORD",
    "CORE_DATABASE_RELAY_PASSWORD",
)


def missing_required(settings: CoreSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    database = settings.database
    present = {
        "CORE_AUTH_AUDIENCE": bool(settings.auth.audience),
        "CORE_NATS_PASSWORD": settings.nats.password is not None,
        "CORE_DATABASE_ORGANIZATION_MANAGER_PASSWORD": database.organization_manager_password
        is not None,
        "CORE_DATABASE_ORGANIZATION_API_PASSWORD": database.organization_api_password is not None,
        "CORE_DATABASE_USER_MANAGER_PASSWORD": database.user_manager_password is not None,
        "CORE_DATABASE_USER_API_PASSWORD": database.user_api_password is not None,
        "CORE_DATABASE_RELAY_PASSWORD": database.relay_password is not None,
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
