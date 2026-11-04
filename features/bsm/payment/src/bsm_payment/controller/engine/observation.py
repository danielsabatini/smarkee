"""Observação pura e estruturada do estado real do método de pagamento no gateway externo."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bsm_payment.controller.drivers.registry import DriverRegistry


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


async def observe_payment(
    resource_id: str,
    *,
    desired: Mapping[str, Any],
    previous_observed: Mapping[str, Any] | None,
    drivers: DriverRegistry,
) -> ObservationResult:
    provider = str(desired.get("provider", "mercadopago"))
    driver = drivers.get(provider)
    record = await driver.observe(
        resource_id,
        desired=desired,
        previous_observed=previous_observed,
    )
    if record is None:
        return ObservationResult(presence="absent", data={})
    return ObservationResult(presence="present", data=record.to_observed_data())
