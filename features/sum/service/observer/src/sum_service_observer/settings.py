"""Configuração do Observer de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_OBSERVER_<SEÇÃO>_<CAMPO>`. Sem default: identificadores do
Zitadel.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ZitadelSettings(_Section):
    base_url: str = "http://identity.smarkee.internal:8080"
    host_header: str = "ipm-dev.smarkee.com.br:8080"
    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    key_file: str = "/run/secrets/zitadel-key.json"
    """Chave JSON da conta `sum-service-observer` (somente leitura)."""

    register_organization_id: str | None = None
    project_ids: dict[str, str] = {}
    """Módulo → projeto de roles que o Observer lê (decisão 0032)."""

    timeout_seconds: float = 5.0


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class CatalogSettings(_Section):
    roles: str | None = None
    """Mesmo catálogo do Manager (serviço → roles), para observar só as roles de cada serviço."""


class HealthSettings(_Section):
    port: int = 8000


class LoopSettings(_Section):
    observation_interval_seconds: int = 300
    """Intervalo da observação periódica (`observationInterval` do `desired`)."""


class SumServiceObserverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_OBSERVER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    zitadel: ZitadelSettings = ZitadelSettings()
    nats: NatsSettings = NatsSettings()
    catalog: CatalogSettings = CatalogSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


REQUIRED_SECRETS = (
    "SUM_SERVICE_OBSERVER_NATS_PASSWORD",
    "SUM_SERVICE_OBSERVER_ZITADEL_REGISTER_ORGANIZATION_ID",
    "SUM_SERVICE_OBSERVER_ZITADEL_PROJECT_IDS",
    "SUM_SERVICE_OBSERVER_CATALOG_ROLES",
)


def missing_required(settings: SumServiceObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "SUM_SERVICE_OBSERVER_NATS_PASSWORD": settings.nats.password is not None,
        "SUM_SERVICE_OBSERVER_CATALOG_ROLES": bool(settings.catalog.roles),
        "SUM_SERVICE_OBSERVER_ZITADEL_REGISTER_ORGANIZATION_ID": bool(
            settings.zitadel.register_organization_id
        ),
        "SUM_SERVICE_OBSERVER_ZITADEL_PROJECT_IDS": bool(settings.zitadel.project_ids),
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
