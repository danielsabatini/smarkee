"""Revalidação da `action` contra o `desired` vigente (`docs/loop/RESOURCE-CONTROL-SECURITY.md`
§7).

O Executor é o último ponto de controle antes do sistema externo: não confia cegamente em quem lhe
enviou a `action`. Puro: recebe o `desired` já lido e devolve o motivo da recusa, ou `None`.
"""

from collections.abc import Mapping
from typing import Any

from core_account.executor.domain.errors import ActionFailedError

OPERATIONS = ("create", "update", "delete")


def revalidate(
    operation: str, action_generation: int | None, desired: Mapping[str, Any] | None
) -> ActionFailedError | None:
    if operation not in OPERATIONS:
        return ActionFailedError("Rejected", retryable=False, message="operation not allowed")
    if desired is None:
        return ActionFailedError(
            "StaleAction", retryable=False, message="no desired for the resource"
        )
    if desired.get("desiredGeneration") != action_generation:
        return ActionFailedError(
            "StaleAction",
            retryable=False,
            message="generation differs from the current desired",
        )
    data: Mapping[str, Any] = desired.get("data") or {}
    if data.get("reconciliation") == "suspended":
        return ActionFailedError(
            "Suspended", retryable=False, message="reconciliation is suspended"
        )
    lifecycle = data.get("lifecycle")
    if (operation == "delete") != (lifecycle == "absent"):
        return ActionFailedError(
            "Rejected", retryable=False, message="operation is not coherent with the desired"
        )
    return None
