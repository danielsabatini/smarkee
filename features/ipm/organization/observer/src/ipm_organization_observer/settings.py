"""Configuração do Observer de Organization (decisão 0015).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo `IPM_ORGANIZATION_OBSERVER_NATS_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS. O Observer
não acessa o SSOT e só **lê** o Zitadel.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None
    consumer_inactive_threshold_seconds: int = 300


class ZitadelSettings(_Section):
    base_url: str = "http://identity.smarkee.internal:8080"
    """Endereço da API do Zitadel na rede interna (não passa pelo gateway público)."""

    host_header: str = "ipm-dev.smarkee.com.br:8080"
    """`Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo."""

    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    """Audience da assertion JWT da conta de serviço."""

    key_file: str = "/run/secrets/zitadel-key.json"
    """Chave JSON da conta de serviço `ipm-organization-observer` (somente leitura)."""

    timeout_seconds: float = 5.0


class PartitionSettings(_Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""


class LoopSettings(_Section):
    observation_interval_seconds: int = 300
    """`observationInterval` (PT5M) de `schemas/ipm/organization/desired`."""

    observation_jitter: float = 0.2
    maximum_concurrent_reads: int = 4
    minimum_seconds_between_reads: float = 1.0
    """Intervalo mínimo entre leituras do mesmo recurso, exceto as causadas por um resultado."""


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/*` (decisão 0018)."""


class OrganizationObserverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_OBSERVER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: NatsSettings = NatsSettings()
    zitadel: ZitadelSettings = ZitadelSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


REQUIRED_SECRETS = ("IPM_ORGANIZATION_OBSERVER_NATS_PASSWORD",)


def missing_required(settings: OrganizationObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {"IPM_ORGANIZATION_OBSERVER_NATS_PASSWORD": settings.nats.password is not None}
    return [name for name in REQUIRED_SECRETS if not present[name]]
