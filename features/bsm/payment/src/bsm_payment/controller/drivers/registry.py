"""Registro modular de drivers de gateways de pagamento por identificador (`provider`)."""

from collections.abc import Iterable

from bsm_payment.controller.drivers.base import PaymentGatewayDriver, ProviderError


class DriverRegistry:
    """Resolve o driver do gateway de pagamento a partir do campo `provider` do recurso."""

    def __init__(self, drivers: Iterable[PaymentGatewayDriver]) -> None:
        self._drivers: dict[str, PaymentGatewayDriver] = {
            driver.provider_name: driver for driver in drivers
        }

    def get(self, provider: str) -> PaymentGatewayDriver:
        driver = self._drivers.get(provider)
        if driver is None:
            raise ProviderError(
                "UnsupportedProvider",
                retryable=False,
                message=f"Provedor de pagamento não suportado: {provider}.",
            )
        return driver
