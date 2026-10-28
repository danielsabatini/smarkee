"""Configuração da API de `sum.service` (decisões 0015, 0033, 0098 e 0100).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `SUM_SERVICE_API_<SEÇÃO>_<CAMPO>`, por exemplo
`SUM_SERVICE_API_MESSAGING_URL` (`docs/data/SCHEMA.md` §8.3). As senhas e o catálogo não têm
default.
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
    """Endereço (da rede interna) em que as chaves públicas são buscadas."""

    host_header: str = "localhost:8080"
    """`Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor."""

    audience: str | None = None
    """ID do projeto de roles do SUM (`roles-sum`): audience dos tokens aceitos. Sem default."""

    jwks_cache_seconds: int = 300


class ApiSettings(Section):
    host: str = "0.0.0.0"  # noqa: S104 (o componente escuta dentro do contêiner; o acesso é pelo gateway)
    port: int = 8000


class CatalogSettings(Section):
    permissions: str | None = None
    """Catálogo serviço → permissões em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`.
    Sem default: a API não sobe sem um catálogo (decisão 0033)."""


class SumServiceApiSettings(RoleSettings):
    model_config = role_config("api")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    catalog: CatalogSettings = CatalogSettings()


def missing_required(settings: SumServiceApiSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_API_",
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
            "CATALOG_PERMISSIONS": bool(settings.catalog.permissions),
        },
    )
