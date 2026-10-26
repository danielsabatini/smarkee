"""Cliente do `ipm.permission`: validações e leitura estrita das respostas."""

from typing import Any

import pytest

from sk.features.ipm.permission import (
    _permission,  # pyright: ignore[reportPrivateUsage]
    validate_description,
    validate_permission_name,
)
from sk.http import ApiUnavailableError


def test_permission_name_validation() -> None:
    assert validate_permission_name("ipm.user.get") == "ipm.user.get"
    for invalid in ("Ipm.User.Get", "sem-ponto", "a.b", "a.b.c.d", "1.2.3"):
        with pytest.raises(ValueError, match="permission name invalid"):
            validate_permission_name(invalid)


def test_permission_description_validation() -> None:
    assert (
        validate_description("Consulta usuários da organização")
        == "Consulta usuários da organização"
    )
    with pytest.raises(ValueError, match="between 1 and 256 characters"):
        validate_description("")
    with pytest.raises(ValueError, match="explain the permission"):
        validate_description("ipm.user.get", name="ipm.user.get")


def test_permission_document_parsing() -> None:
    raw: dict[str, Any] = {
        "resourceId": "p-1",
        "resourceVersion": "1",
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "specification": {
                "name": "ipm.user.get",
                "description": "Consulta usuários",
                "grantable": True,
                "deletionProtection": False,
                "status": "active",
            },
        },
    }
    perm = _permission(raw)
    assert perm.resource_id == "p-1"
    assert perm.name == "ipm.user.get"
    assert perm.grantable is True
    assert perm.deletion_protection is False
    assert perm.status == "active"


def test_permission_missing_specification_fields() -> None:
    raw: dict[str, Any] = {
        "resourceId": "p-1",
        "resourceVersion": "1",
        "phase": "Ready",
        "desired": {"lifecycle": "present", "specification": {}},
    }
    with pytest.raises(ApiUnavailableError):
        _permission(raw)
