"""Configuração do Executor de `sum.service` (decisões 0015, 0032 e 0033).

Nome da variável: `SUM_SERVICE_EXECUTOR_<SEÇÃO>_<CAMPO>`. Sem default: senhas, identificadores do
Zitadel e
o catálogo.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class ZitadelSettings(_Section):
    base_url: str = "http://identity.smarkee.internal:8080"
    host_header: str = "ipm-dev.smarkee.com.br:8080"
    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    key_file: str = "/run/secrets/zitadel-key.json"
    """Chave JSON da conta `sum-service-executor`: `PROJECT_GRANT_OWNER` só no Grant de `roles-
    ipm`."""

    register_organization_id: str | None = None
    project_ids: dict[str, str] = {}
    """Módulo → projeto de roles que o Executor pode conceder (decisão 0032). Hoje só `ipm`."""

    timeout_seconds: float = 10.0


class CatalogSettings(_Section):
    roles: str | None = None
    """Mesmo catálogo do Manager: as roles de um serviço, para revogar ao desligar."""


class PartitionSettings(_Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do broker): um consumer e um laço por partição."""


class HealthSettings(_Section):
    port: int = 8000


class SumServiceExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_EXECUTOR_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: NatsSettings = NatsSettings()
    zitadel: ZitadelSettings = ZitadelSettings()
    catalog: CatalogSettings = CatalogSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = (
    "SUM_SERVICE_EXECUTOR_NATS_PASSWORD",
    "SUM_SERVICE_EXECUTOR_ZITADEL_REGISTER_ORGANIZATION_ID",
    "SUM_SERVICE_EXECUTOR_ZITADEL_PROJECT_IDS",
    "SUM_SERVICE_EXECUTOR_CATALOG_ROLES",
)


def missing_required(settings: SumServiceExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "SUM_SERVICE_EXECUTOR_NATS_PASSWORD": settings.nats.password is not None,
        "SUM_SERVICE_EXECUTOR_ZITADEL_REGISTER_ORGANIZATION_ID": bool(
            settings.zitadel.register_organization_id
        ),
        "SUM_SERVICE_EXECUTOR_ZITADEL_PROJECT_IDS": bool(settings.zitadel.project_ids),
        "SUM_SERVICE_EXECUTOR_CATALOG_ROLES": bool(settings.catalog.roles),
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
