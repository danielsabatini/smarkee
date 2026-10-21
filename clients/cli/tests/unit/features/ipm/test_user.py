"""Cliente do `ipm.user`: validação das roles e leitura estrita das respostas."""

from typing import Any

import pytest

from sk.features.ipm.user import _user, validate_roles  # pyright: ignore[reportPrivateUsage]
from sk.http import ApiUnavailableError


def test_roles_are_a_sorted_set_in_the_contract_pattern() -> None:
    assert validate_roles(["ipm.user.list", "ipm.user.get", "ipm.user.get"]) == [
        "ipm.user.get",
        "ipm.user.list",
    ]
    for invalid in (["Ipm.User.Get"], ["sem-ponto"], ["a.b.c.d"]):
        with pytest.raises(ValueError, match="role invalid") as raised:
            validate_roles(invalid)
        assert invalid[0] not in str(raised.value)
    with pytest.raises(ValueError, match="too many"):
        validate_roles([f"ipm.user.r{index}" for index in range(65)])


def document(**desired: Any) -> dict[str, Any]:
    return {
        "resourceId": "u-1",
        "resourceVersion": "2",
        "phase": "Deleting",
        "desired": {"lifecycle": "absent", "organizationId": "o-1", "roles": [], **desired},
    }


def test_a_user_being_removed_has_no_email_and_is_unprotected_by_default() -> None:
    user = _user(document())
    assert (user.email, user.deletion_protection, user.user_state) == (None, False, None)


def test_a_response_without_roles_is_refused() -> None:
    body = document()
    del body["desired"]["roles"]
    with pytest.raises(ApiUnavailableError):
        _user(body)
