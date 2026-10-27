"""Cliente do `ipm.role`: validações e leitura estrita das respostas."""

from typing import Any

import pytest

from sk.features.ipm.role import (
    _role,  # pyright: ignore[reportPrivateUsage]
    validate_description,
    validate_permissions_list,
    validate_role_name,
)
from sk.http import ApiUnavailableError


def test_role_name_validation() -> None:
    assert validate_role_name("ipm.userAdmin") == "ipm.userAdmin"
    assert validate_role_name("bsm.accountViewer") == "bsm.accountViewer"
    for invalid in ("Ipm.UserAdmin", "sem-ponto", "a", "a.b.c"):
        with pytest.raises(ValueError, match="role name invalid"):
            validate_role_name(invalid)


def test_role_description_validation() -> None:
    assert validate_description("Administrador de usuários") == "Administrador de usuários"
    with pytest.raises(ValueError, match="between 1 and 256 characters"):
        validate_description("")
    with pytest.raises(ValueError, match="explain the role"):
        validate_description("ipm.userAdmin", name="ipm.userAdmin")


def test_role_permissions_list_validation() -> None:
    assert validate_permissions_list(["ipm.user.get", "ipm.user.list", "ipm.user.get"]) == [
        "ipm.user.get",
        "ipm.user.list",
    ]
    with pytest.raises(ValueError, match="at least one permission"):
        validate_permissions_list([])
    with pytest.raises(ValueError, match="permission invalid"):
        validate_permissions_list(["invalid_perm"])


def test_role_document_parsing() -> None:
    raw: dict[str, Any] = {
        "resourceId": "r-1",
        "resourceVersion": "2",
        "desiredGeneration": 2,
        "observedGeneration": 2,
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "specification": {
                "name": "ipm.userAdmin",
                "description": "Administrador de usuários",
                "permissions": ["ipm.user.create", "ipm.user.get"],
                "deletionProtection": True,
                "status": "active",
            },
        },
    }
    role = _role(raw)
    assert role.resource_id == "r-1"
    assert role.name == "ipm.userAdmin"
    assert role.permissions == ("ipm.user.create", "ipm.user.get")
    assert role.deletion_protection is True
    assert role.role_type == "custom"  # sem roleType (dados antigos), vale custom
    assert (role.desired_generation, role.observed_generation) == (2, 2)
    assert role.failure_reason is None


def test_role_parser_without_observed_generation_or_with_a_failed_condition() -> None:
    raw: dict[str, Any] = {
        "resourceId": "r-1",
        "resourceVersion": "1",
        "desiredGeneration": 1,
        "phase": "Failed",
        "conditions": [{"status": "False", "reason": "Rejected"}],
        "desired": {
            "lifecycle": "present",
            "name": "ipm.userAdmin",
            "description": "Administrador de usuários",
            "permissions": [],
        },
    }
    role = _role(raw)
    assert role.observed_generation is None
    assert role.failure_reason == "Rejected"


def test_role_type_is_read_from_the_api() -> None:
    raw: dict[str, Any] = {
        "resourceId": "r-1",
        "resourceVersion": "1",
        "desiredGeneration": 1,
        "observedGeneration": 1,
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "name": "ipm.userAdmin",
            "roleType": "predefined",
            "description": "Administrador de usuários",
            "permissions": ["ipm.user.get"],
        },
    }
    assert _role(raw).role_type == "predefined"


def test_role_missing_specification_fields() -> None:
    raw: dict[str, Any] = {
        "resourceId": "r-1",
        "resourceVersion": "1",
        "desiredGeneration": 1,
        "phase": "Ready",
        "desired": {"lifecycle": "present", "specification": {"name": "ipm.userAdmin"}},
    }
    with pytest.raises(ApiUnavailableError):
        _role(raw)
