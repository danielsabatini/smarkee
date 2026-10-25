"""Testes unitários da decisão do Reconciler de `ipm.permission` (decisão 0083)."""

from datetime import UTC, datetime

from ipm_permission.reconciler.domain.decision import (
    DesiredState,
    ObservedState,
    ResourceState,
    decide,
)
from ipm_permission.reconciler.settings import LoopSettings

FIXED_NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


def _desired(
    *,
    lifecycle: str = "present",
    name: str = "ipm.user.bind",
    description: str = "Atribuir e alterar permissões.",
    grantable: bool = True,
) -> DesiredState:
    return DesiredState(
        message_id="msg-desired-1",
        generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        name=name,
        description=description,
        grantable=grantable,
        requested_by="operator-1",
        correlation_id="corr-1",
    )


def _observed(
    *,
    presence: str = "present",
    name: str | None = "ipm.user.bind",
    description: str | None = "Atribuir e alterar permissões.",
    group: str | None = "ipm",
) -> ObservedState:
    return ObservedState(
        message_id="msg-observed-1",
        presence=presence,
        observed_at=FIXED_NOW,
        causation_id=None,
        name=name,
        description=description,
        group=group,
    )


def test_decide_create_when_absent_in_zitadel() -> None:
    state = ResourceState(
        desired=_desired(),
        observed=_observed(presence="absent", name=None, description=None, group=None),
    )
    decision = decide(state, FIXED_NOW, LoopSettings())
    assert decision is not None
    assert decision.operation == "create"


def test_decide_update_when_description_or_group_drifts() -> None:
    state = ResourceState(
        desired=_desired(description="Nova descrição."),
        observed=_observed(description="Antiga."),
    )
    decision = decide(state, FIXED_NOW, LoopSettings())
    assert decision is not None
    assert decision.operation == "update"
    assert decision.fields == ("description",)


def test_decide_noop_when_converged() -> None:
    state = ResourceState(desired=_desired(), observed=_observed())
    assert decide(state, FIXED_NOW, LoopSettings()) is None
