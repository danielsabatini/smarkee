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
                "organizationId": "org-acme",
                "name": "ipm.userAdmin",
                "description": "Administração de usuários.",
                "permissions": ["ipm.user.get", "ipm.user.bind", "ipm.user.get"],
            },
        },
    )
    desired = policy.desired_for_create(req, "operator-1")
    assert desired == {
        "lifecycle": "present",
        "organizationId": "org-acme",
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
    # Única por Organization e também contra as predefinidas (`core`).
    assert unique.scope_field == "organizationId"
    assert unique.scope_values == ("org-acme", "core")


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


def _create(organization_id: str, **extra: object) -> dict[str, object]:
    return {
        "operationId": "01950000-0000-7000-8000-000000000004",
        "requestDigest": DIGEST,
        **extra,
        "specification": {
            "organizationId": organization_id,
            "name": "acme.billing",
            "description": "Cobrança.",
            "permissions": ["ipm.user.get"],
        },
    }


def test_core_organization_is_reserved_to_predefined_roles() -> None:
    with pytest.raises(PermanentMessageError):
        RolePolicy().parse("create", _create("core"))


def test_owner_quota_only_on_create_with_a_limit() -> None:
    policy = RolePolicy()
    with_limit = policy.parse("create", _create("org-acme", organizationQuotaLimit=10))
    desired = policy.desired_for_create(with_limit, "u")
    quota = policy.owner_quota(with_limit, desired)
    assert quota is not None
    assert (quota.field, quota.owner, quota.limit) == ("organizationId", "org-acme", 10)

    without_limit = policy.parse("create", _create("org-acme"))  # operador: sem cota
    assert policy.owner_quota(without_limit, desired) is None


def test_roles_without_organization_are_treated_as_core() -> None:
    policy = RolePolicy()
    legacy = {"lifecycle": "present", "name": "ipm.userAdmin"}
    unique = policy.unique_value(legacy)
    assert unique is not None
    assert unique.scope_values == ("core",)
