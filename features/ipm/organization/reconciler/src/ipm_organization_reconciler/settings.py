"""Configuração do Reconciler de Organization (decisão 0015).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_RECONCILER_<SEÇÃO>_<CAMPO>`, por exemplo `IPM_ORGANIZATION_RECONCILER_NATS_URL`
(`docs/SCHEMA.md` §8.3). A senha do NATS não tem default. O Reconciler não acessa o SSOT.
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


class LoopSettings(_Section):
    """Parâmetros do loop do tipo (`x-resourceParameters` de `schemas/ipm/organization/desired`)."""

    observation_validity_seconds: int = 600
    """`observationValidity` (PT10M): idade máxima de um `observed` para decidir."""

    action_deadline_seconds: int = 120
    """`actionDeadline` (PT2M): prazo da `action` pendente e da espera pela observação causada."""

    reevaluation_interval_seconds: int = 30
    """Período da reavaliação periódica de todos os recursos (com jitter)."""

    reevaluation_jitter: float = 0.2
    failure_backoff_seconds: int = 5
    """Atraso após o primeiro `failed`; dobra a cada falha seguida, até o máximo."""

    failure_backoff_maximum_seconds: int = 300


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/*` (decisão 0018)."""


class OrganizationReconcilerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_RECONCILER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: NatsSettings = NatsSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = ("IPM_ORGANIZATION_RECONCILER_NATS_PASSWORD",)


def missing_required(settings: OrganizationReconcilerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {"IPM_ORGANIZATION_RECONCILER_NATS_PASSWORD": settings.nats.password is not None}
    return [name for name in REQUIRED_SECRETS if not present[name]]
