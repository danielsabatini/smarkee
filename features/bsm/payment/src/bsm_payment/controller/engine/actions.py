"""Execução idempotente das operações do método de pagamento no gateway externo (decisão 0096)."""

from collections.abc import Mapping
from typing import Any

from bsm_payment.controller.drivers.base import ProviderError
from bsm_payment.controller.drivers.registry import DriverRegistry


class ActionFailedError(Exception):
    def __init__(self, reason: str, *, retryable: bool = False, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message


async def execute(
    operation: str,
    resource_id: str,
    desired: Mapping[str, Any],
    *,
    previous_observed: Mapping[str, Any] | None,
    drivers: DriverRegistry,
) -> dict[str, Any]:
    provider = str(desired.get("provider", "mercadopago"))
    try:
        driver = drivers.get(provider)
        if operation == "create":
            created = await driver.create(resource_id, desired=desired)
            return created.to_observed_data()
        if operation == "update":
            updated = await driver.update(
                resource_id,
                desired=desired,
                previous_observed=previous_observed,
            )
            return updated.to_observed_data()
        if operation == "delete":
            await driver.delete(
                resource_id,
                desired=desired,
                previous_observed=previous_observed,
            )
            return {}
    except ProviderError as error:
        raise ActionFailedError(
            error.reason,
            retryable=error.retryable,
            message=error.message,
        ) from error

    raise ActionFailedError(f"unsupported_operation:{operation}")
