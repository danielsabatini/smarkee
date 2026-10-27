"""Configuração da API de Billing Account (decisões 0015, 0082, 0098 e 0100).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `BSM_ACCOUNT_API_<SEÇÃO>_<CAMPO>`, por exemplo
`BSM_ACCOUNT_API_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas não têm default.
"""

from bsm_account.common.settings import (
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

    userinfo_url: str = "http://localhost:8000/oidc/v1/userinfo"

    host_header: str = "localhost:8080"
    """`Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor."""

    audience: str | None = None
    """ID do projeto de roles do módulo (`roles-bsm`, audience dos access tokens). Sem default."""

    jwks_cache_seconds: int = 300
    userinfo_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    account_quota: int | None = None
    """Cota opcional de Billing Accounts por solicitante."""


class AccountApiSettings(RoleSettings):
    model_config = role_config("api")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()


def missing_required(settings: AccountApiSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "BSM_ACCOUNT_API_",
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
