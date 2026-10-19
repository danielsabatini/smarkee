"""Revalidação da `action` contra o `desired` vigente (`docs/RESOURCE-CONTROL-SECURITY.md` §7).

O Executor é o último ponto de controle antes do Zitadel: não confia cegamente em quem lhe enviou a
`action`. Puro: recebe o `desired` já lido e devolve o motivo da recusa, ou `None`.

No SUM, ligar e desligar são a mesma operação `update` da ação: o que muda é o `lifecycle` do
`desired`. Por isso não há a coerência entre `delete` e `absent` que o User confere.
"""

from collections.abc import Mapping
from typing import Any

from sum_service.executor.domain.errors import ActionFailedError

OPERATIONS = ("update",)
LIFECYCLES = ("present", "absent")


def revalidate(
    operation: str, action_generation: int, desired: Mapping[str, Any] | None
) -> ActionFailedError | None:
    if operation not in OPERATIONS:
        return ActionFailedError("Rejected", retryable=False, message="operation not allowed")
    if desired is None:
        return ActionFailedError(
            "StaleAction", retryable=False, message="no desired for the resource"
        )
    if desired.get("generation") != action_generation:
        return ActionFailedError(
            "StaleAction",
            retryable=False,
            message="generation differs from the current desired",
        )
    if desired.get("reconciliation") == "suspended":
        return ActionFailedError(
            "Suspended", retryable=False, message="reconciliation is suspended"
        )
    # Sem `lifecycle` válido não há como saber se é para ligar ou desligar: não se assume nenhum.
    if desired.get("lifecycle") not in LIFECYCLES:
        return ActionFailedError(
            "Rejected", retryable=False, message="desired has no valid lifecycle"
        )
    if not desired.get("owner") or not desired.get("service"):
        return ActionFailedError(
            "Rejected", retryable=False, message="desired has no owner or service"
        )
    return None
