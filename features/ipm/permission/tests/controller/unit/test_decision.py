"""Testes unitários da decisão pura de reconciliação no Controller (decisão 0096)."""

from ipm_permission.controller.domain.decision import DesiredState, ObservedState, decide

NAME = "ipm.thing.get"
DESCRIPTION = "Ler coisas"


def desired(lifecycle: str = "present", description: str = DESCRIPTION) -> DesiredState:
    return DesiredState(lifecycle=lifecycle, name=NAME, description=description)


def present(description: str = DESCRIPTION, group: str = "ipm") -> ObservedState:
    return ObservedState(presence="present", name=NAME, description=description, group=group)


def test_missing_permission_is_created() -> None:
    decision = decide(desired(), ObservedState(presence="absent"))
    assert decision is not None
    assert decision.operation == "create"
    assert decision.reason == "resource_absent"
    assert decision.fields == ("lifecycle",)


def test_converged_permission_requires_no_action() -> None:
    assert decide(desired(), present()) is None


def test_description_drift_triggers_update() -> None:
    decision = decide(desired(description="Outra"), present())
    assert decision is not None
    assert decision.operation == "update"
    assert decision.fields == ("description",)


def test_group_drift_triggers_update() -> None:
    decision = decide(desired(), present(group="outro"))
    assert decision is not None
    assert decision.operation == "update"
    assert decision.fields == ("group",)


def test_lifecycle_absent_triggers_delete() -> None:
    decision = decide(desired("absent"), present())
    assert decision is not None
    assert decision.operation == "delete"
    assert decision.reason == "lifecycle_absent"


def test_already_absent_requires_no_action() -> None:
    assert decide(desired("absent"), ObservedState(presence="absent")) is None


def test_unknown_presence_defers_decision() -> None:
    assert decide(desired(), ObservedState(presence="unknown")) is None
