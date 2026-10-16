"""Configuração do Reconciler de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_RECONCILER_<SEÇÃO>_<CAMPO>`. Os parâmetros do loop vêm do
contrato `desired` (`x-resourceParameters`). Só a senha do NATS não tem default.
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
    """Tempo sem uso após o qual o servidor remove o consumer da instância (`docs/NATS.md` §7.4)."""


class HealthSettings(_Section):
    port: int = 8000


class LoopSettings(_Section):
    """Parâmetros do loop (`x-resourceParameters` do `desired`, decisão 0033)."""

    observation_interval_seconds: int = 300
    observation_validity_seconds: int = 600
    action_deadline_seconds: int = 120
    failure_limit: int = 5
    failure_backoff_seconds: int = 30
    failure_backoff_maximum_seconds: int = 600
    reevaluation_interval_seconds: int = 15
    """Período da reavaliação periódica de todos os recursos (com jitter)."""

    reevaluation_jitter: float = 0.2


class SumServiceReconcilerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_RECONCILER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: NatsSettings = NatsSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


REQUIRED_SECRETS = ("SUM_SERVICE_RECONCILER_NATS_PASSWORD",)


def missing_required(settings: SumServiceReconcilerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {"SUM_SERVICE_RECONCILER_NATS_PASSWORD": settings.nats.password is not None}
    return [name for name in REQUIRED_SECRETS if not present[name]]
