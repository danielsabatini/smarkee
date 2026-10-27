"""Configuração da API de Service Account (decisões 0015 e 0077).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `IPM_SERVICEACCOUNT_API_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_SERVICEACCOUNT_API_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas não têm default.
"""

from ipm_serviceaccount.common.settings import (
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
    """ID do projeto `roles-ipm` (audience dos access tokens). Sem default."""

    jwks_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (o componente escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000
    serviceaccount_quota: int = 5
    """Service accounts por Organization para quem não é operador (decisão 0094; provisório)."""


class PeersSettings(Section):
    """Receivers de Organization e User, na rede interna: confirmam o solicitante com o token dele."""

    organizations_url: str = "http://localhost:8000"
    users_url: str = "http://localhost:8000"
    """Receiver de User: reconhece o usuário humano da Organization (decisão 0094)."""

    timeout_seconds: float = 5.0


class ServiceaccountApiSettings(RoleSettings):
    model_config = role_config("api")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    peers: PeersSettings = PeersSettings()


def missing_required(settings: ServiceaccountApiSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_SERVICEACCOUNT_API_",
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
