"""Configuração do Controller de Payment (`bsm.payment`, decisão 0096).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `BSM_PAYMENT_CONTROLLER_<SEÇÃO>_<CAMPO>`.
"""

from bsm_payment.common.database import DatabaseSettings
from bsm_payment.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class MercadoPagoSettings(Section):
    """Configuração do driver do gateway de pagamento Mercado Pago (API v1)."""

    base_url: str = "https://api.mercadopago.com"
    """Endereço base da API do Mercado Pago."""

    access_token: str | None = None
    """Access Token do Mercado Pago (`TEST-...` em sandbox/dev; vem de segredo em K8s)."""

    timeout_seconds: float = 10.0
    """Timeout das chamadas HTTP ao gateway de pagamento."""

    simulation_mode: bool = True
    """Em dev/CI local, simula a custódia e validação do token sem tráfego externo."""


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância reconcilia só `hash mod count == index`."""


class LoopSettings(Section):
    reevaluation_interval_seconds: int = 300
    """Intervalo periódico de reavaliação de todos os recursos gerenciados."""

    reevaluation_jitter: float = 0.2
    workers: int = 2
    """Número de workers simultâneos de reconciliação."""

    failure_limit: int = 5
    """Falhas de ação até suspender a reconciliação (`SSOT.md` §10.3)."""

    progress_deadline_seconds: int = 300
    """Prazo de progresso para a geração convergir antes de marcar Failed."""


class PaymentControllerSettings(RoleSettings):
    model_config = role_config("controller")

    database: DatabaseSettings = DatabaseSettings()
    messaging: StateMessagingSettings = StateMessagingSettings()
    mercadopago: MercadoPagoSettings = MercadoPagoSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: PaymentControllerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "BSM_PAYMENT_CONTROLLER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "MERCADOPAGO_ACCESS_TOKEN": (
                settings.mercadopago.simulation_mode or bool(settings.mercadopago.access_token)
            ),
        },
    )
