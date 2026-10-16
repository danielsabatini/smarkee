"""Configuração do Observer de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_OBSERVER_<SEÇÃO>_<CAMPO>`. Sem default: identificadores do
Zitadel.
"""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
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
    consumer_inactive_threshold_seconds: int = 300
    """Tempo sem uso após o qual o servidor remove o consumer da instância (`docs/NATS.md` §7.4)."""


class CatalogSettings(_Section):
    roles: str | None = None
    """Mesmo catálogo do Manager (serviço → roles), para observar só as roles de cada serviço."""


class HealthSettings(_Section):
    port: int = 8000


class PartitionSettings(_Section):
    index: int = Field(default=0, ge=0)
    count: int = Field(default=1, ge=1)
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""

    @model_validator(mode="after")
    def _index_is_inside_the_count(self) -> PartitionSettings:
        if self.index >= self.count:
            raise ValueError("a partição (index) deve ser menor que a quantidade (count)")
        return self


class LoopSettings(_Section):
    observation_interval_seconds: int = 300
    """Intervalo da observação periódica (`observationInterval` do `desired`)."""

    observation_jitter: float = 0.2
    """Fração de variação do intervalo, para as instâncias não observarem todas ao mesmo tempo."""


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
    partition: PartitionSettings = PartitionSettings()


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
