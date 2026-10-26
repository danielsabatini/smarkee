"""Configuração do Receiver de Role (decisões 0015, 0083 e 0092).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `IPM_ROLE_RECEIVER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ROLE_RECEIVER_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas não têm default.
"""

from ipm_role.common.settings import (
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
    """ID do projeto `roles-ipm` (organização `core` do Zitadel): obrigatório, sem default."""

    jwks_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (contêiner atrás do gateway; não é exposto direto)
    port: int = 8000
    role_quota: int = 10
    """Roles `custom` por Organization para quem não é operador (decisão 0092)."""


class PeersSettings(Section):
    """Receivers de Organization, User, Group e ServiceAccount na rede interna."""

    organizations_url: str = "http://localhost:8000"
    users_url: str = "http://localhost:8000"
    groups_url: str = "http://localhost:8000"
    serviceaccounts_url: str = "http://localhost:8000"
    timeout_seconds: float = 5.0


class RoleReceiverSettings(RoleSettings):
    model_config = role_config("receiver")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    peers: PeersSettings = PeersSettings()


def missing_required(settings: RoleReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ROLE_RECEIVER_",
        {
            "DATABASE_PASSWORD": settings.database.password is not None,
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "AUTH_AUDIENCE": bool(settings.auth.audience),
        },
    )
