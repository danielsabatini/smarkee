"""Cliente do `ipm.user`: validação das permissões e leitura estrita das respostas."""

from typing import Any

import pytest

from sk.features.ipm.user import (
    _user,  # pyright: ignore[reportPrivateUsage]
    validate_roles,
)


def test_roles_are_a_sorted_set_in_the_contract_pattern() -> None:
    assert validate_roles(["ipm.userViewer", "ipm.userAdmin", "ipm.userViewer"]) == [
        "ipm.userAdmin",
        "ipm.userViewer",
    ]
    for invalid in (["Ipm.UserAdmin"], ["sem-ponto"], ["a.b.c"]):
        with pytest.raises(ValueError, match="role invalid") as raised:
            validate_roles(invalid)
        assert invalid[0] not in str(raised.value)
    with pytest.raises(ValueError, match="too many"):
        validate_roles([f"ipm.r{index}" for index in range(33)])


def document(**desired: Any) -> dict[str, Any]:
    return {
        "resourceId": "u-1",
        "resourceVersion": "2",
        "desiredGeneration": 1,
        "observedGeneration": 1,
        "phase": "Deleting",
        "desired": {
            "lifecycle": "absent",
            "organizationId": "o-1",
            **desired,
        },
    }


def test_a_user_being_removed_has_no_email_and_is_unprotected_by_default() -> None:
    user = _user(document())
    assert (user.email, user.deletion_protection, user.user_state) == (None, False, None)
    assert (user.desired_generation, user.observed_generation) == (1, 1)
    assert user.failure_reason is None


def test_user_parser_without_observed_generation() -> None:
    body = document()
    del body["observedGeneration"]
    user = _user(body)
    assert user.observed_generation is None


def test_effective_permissions_come_from_the_observed_state() -> None:
    body = document()
    assert _user(body).permissions == ()  # ainda não observado

    body["observed"] = {"effectivePermissions": ["ipm.user.get"]}
    assert _user(body).permissions == ("ipm.user.get",)
