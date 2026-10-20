"""Configuração do Receiver de `sum.service` (decisões 0015 e 0033).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
audience não têm default.
"""

from sum_service.common.settings import (
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
    host_header: str = "localhost:8080"
    audience: str | None = None
    """ID do projeto de roles do SUM (`roles-sum`): audience dos tokens aceitos."""

    jwks_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000


class PeersSettings(Section):
    """Receivers dos outros módulos, na rede interna, consultados ao desabilitar um serviço."""

    organizations_url: str = "http://localhost:8000"
    timeout_seconds: float = 5.0


class SumServiceReceiverSettings(RoleSettings):
    model_config = role_config("receiver")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    peers: PeersSettings = PeersSettings()


def missing_required(settings: SumServiceReceiverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_RECEIVER_",
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
