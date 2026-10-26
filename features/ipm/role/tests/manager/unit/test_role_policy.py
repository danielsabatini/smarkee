"""Testes unitários da política de `ipm.role` no Manager (decisão 0083)."""

import pytest

from ipm_role.manager.domain.errors import PermanentMessageError
from ipm_role.manager.domain.role import RolePolicy

DIGEST = "a" * 64


def test_parse_create_and_build_desired_normalizes_permissions() -> None:
    policy = RolePolicy()
    req = policy.parse(
        "create",
        {
            "operationId": "01950000-0000-7000-8000-000000000001",
            "requestDigest": DIGEST,
            "specification": {
                "name": "ipm.userAdmin",
                "description": "Administração de usuários.",
                "permissions": ["ipm.user.get", "ipm.user.bind", "ipm.user.get"],
            },
        },
    )
    desired = policy.desired_for_create(req, "operator-1")
    assert desired == {
        "lifecycle": "present",
        "name": "ipm.userAdmin",
        "roleType": "custom",
        "description": "Administração de usuários.",
        "permissions": ["ipm.user.bind", "ipm.user.get"],
        "deletionProtection": True,
    }
    unique = policy.unique_value(desired)
    assert unique is not None
    assert unique.field == "name"
    assert unique.value == "ipm.userAdmin"


def test_update_and_delete_desired() -> None:
    policy = RolePolicy()
    current = {
        "lifecycle": "present",
        "name": "ipm.userAdmin",
        "description": "Antiga.",
        "permissions": ["ipm.user.get"],
        "deletionProtection": True,
    }
    req = policy.parse(
        "update",
        {
            "operationId": "01950000-0000-7000-8000-000000000002",
            "requestDigest": DIGEST,
            "resourceVersion": "1",
            "specification": {
                "description": "Nova.",
                "permissions": ["ipm.user.list", "ipm.user.get"],
                "deletionProtection": False,
            },
        },
    )
    updated = policy.desired_for_update(current, req)
    assert updated["description"] == "Nova."
    assert updated["permissions"] == ["ipm.user.get", "ipm.user.list"]
    assert policy.deletion_protected(updated) is False
    assert policy.is_converged(
        updated,
        "present",
        {
            "name": "ipm.userAdmin",
            "description": "Nova.",
            "permissions": ["ipm.user.get", "ipm.user.list"],
            "deletionProtection": False,
        },
    )

    deleted = policy.desired_for_delete(updated)
    assert deleted["lifecycle"] == "absent"
    assert policy.unique_value(deleted) is None
    assert policy.is_converged(deleted, "absent", {})


def test_parse_update_without_changes_raises_permanent_error() -> None:
    policy = RolePolicy()
    with pytest.raises(PermanentMessageError):
        policy.parse(
            "update",
            {
                "operationId": "01950000-0000-7000-8000-000000000003",
                "requestDigest": DIGEST,
                "resourceVersion": "1",
            },
        )
