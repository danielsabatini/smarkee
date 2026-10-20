"""Configuração do Receiver de Organization (decisão 0015).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `IPM_ORGANIZATION_RECEIVER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_RECEIVER_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from ipm_organization.common.settings import DatabaseSettings as CommonDatabaseSettings
from ipm_organization.common.settings import (
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "ipm_organization_receiver_login"
    """Papel de login do Receiver: só `SELECT` nas views do tipo (`docs/POSTGRESQL.md` §14.2)."""


class AuthSettings(Section):
    issuer: str = "http://localhost:8080"
    """Valor esperado de `iss`: o endereço público do provedor de identidade."""

    jwks_url: str = "http://localhost:8000/oauth/v2/keys"
    """Endereço (da rede interna) em que as chaves públicas são buscadas."""

    userinfo_url: str = "http://localhost:8000/oidc/v1/userinfo"

    host_header: str = "localhost:8080"
    """`Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor."""

    audience: str | None = None
    """ID do projeto da plataforma (audience dos access tokens). Sem default."""

    jwks_cache_seconds: int = 300
    userinfo_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (o componente escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000
    organization_quota: int = 1
    """Organizations por dono para quem não é operador (decisão 0010)."""


class OrganizationReceiverSettings(RoleSettings):
    model_config = role_config("receiver")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()


def missing_required(settings: OrganizationReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_RECEIVER_",
        {
            "AUTH_AUDIENCE": bool(settings.auth.audience),
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
