"""Configuração da API de Account (decisões 0015, 0098 e 0100).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `CORE_ACCOUNT_API_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_API_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas não têm default.
"""

from core_account.api.domain.account import DEFAULT_PLATFORM_PERMISSIONS
from core_account.common.settings import (
    DatabaseSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class AuthSettings(Section):
    issuer: str = "http://localhost:8080"
    """Valor esperado de `iss`: o endereço público do provedor de identidade."""

    jwks_url: str = "http://localhost:8000/oauth/v2/keys"
    """Endereço (da rede interna) em que as chaves públicas são buscadas."""

    host_header: str = "localhost:8080"
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


class PlatformSettings(Section):
    permissions: tuple[str, ...] = DEFAULT_PLATFORM_PERMISSIONS
    """Permissões gravadas no `desired` do usuário cadastrado (decisão 0025). Lista em JSON."""


class AccountApiSettings(RoleSettings):
    model_config = role_config("api")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    platform: PlatformSettings = PlatformSettings()


def missing_required(settings: AccountApiSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_API_",
        {
            "AUTH_AUDIENCE": bool(settings.auth.audience),
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
