"""Testes unitários da política de `ipm.group` no Manager (decisão 0088)."""

import pytest

from ipm_group.common.catalog import RolesCatalog
from ipm_group.manager.domain.errors import PermanentMessageError
from ipm_group.manager.domain.group import GroupPolicy

DIGEST = "a" * 64
ORGANIZATION = "01950000-0000-7000-8000-0000000000aa"


def _create(roles: list[str] | None = None, quota: int | None = None) -> dict[str, object]:
    data: dict[str, object] = {
        "operationId": "01950000-0000-7000-8000-000000000001",
        "requestDigest": DIGEST,
        "specification": {
            "organizationId": ORGANIZATION,
            "name": "auditors",
            "description": " Auditores da Organization. ",
            "roles": roles if roles is not None else ["ipm.userViewer", "core.accountViewer"],
        },
    }
    if quota is not None:
        data["organizationQuotaLimit"] = quota
    return data


def test_parse_create_normalizes_and_builds_the_desired() -> None:
    policy = GroupPolicy()
    request = policy.parse("create", _create(["ipm.userViewer", "core.accountViewer"]))
    desired = policy.desired_for_create(request, "operator-1")
    assert desired == {
        "lifecycle": "present",
        "organizationId": ORGANIZATION,
        "name": "auditors",
        "description": "Auditores da Organization.",
        "roles": ["core.accountViewer", "ipm.userViewer"],
        "deletionProtection": False,
    }
    unique = policy.unique_value(desired)
    assert unique is not None
    assert (unique.field, unique.value, unique.scope_value) == ("name", "auditors", ORGANIZATION)
    assert unique.lock_key == f"ipm.group.name:{ORGANIZATION}:auditors"


def test_roles_outside_the_catalog_are_invalid() -> None:
    policy = GroupPolicy(RolesCatalog({"ipm.userViewer": ["ipm.user.get"]}))
    assert not policy.invalid({"roles": ["ipm.userViewer"]})
    assert policy.invalid({"roles": ["ipm.userViewer", "ipm.unknownRole"]})


def test_owner_quota_only_applies_to_create_with_a_limit() -> None:
    policy = GroupPolicy()
    with_limit = policy.parse("create", _create(quota=3))
    desired = policy.desired_for_create(with_limit, "operator-1")
    quota = policy.owner_quota(with_limit, desired)
    assert quota is not None
    assert (quota.owner, quota.limit) == (ORGANIZATION, 3)
    assert policy.owner_quota(policy.parse("create", _create()), desired) is None


def test_update_and_delete_desired() -> None:
    policy = GroupPolicy()
    current = {
        "lifecycle": "present",
        "organizationId": ORGANIZATION,
        "name": "auditors",
        "description": "Antiga.",
        "roles": ["ipm.userViewer"],
        "deletionProtection": True,
    }
    request = policy.parse(
        "update",
        {
            "operationId": "01950000-0000-7000-8000-000000000002",
            "requestDigest": DIGEST,
            "resourceVersion": "1",
            "specification": {
                "description": "Nova.",
                "roles": ["ipm.userViewer", "core.accountViewer"],
                "deletionProtection": False,
            },
        },
    )
    updated = policy.desired_for_update(current, request)
    assert updated["description"] == "Nova."
    assert updated["roles"] == ["core.accountViewer", "ipm.userViewer"]
    assert policy.deletion_protected(updated) is False
    assert policy.is_converged(
        updated,
        "present",
        {
            "name": "auditors",
            "description": "Nova.",
            "roles": ["ipm.userViewer", "core.accountViewer"],
            "deletionProtection": False,
        },
    )

    deleted = policy.desired_for_delete(updated)
    assert deleted["lifecycle"] == "absent"
    assert policy.unique_value(deleted) is None
    assert policy.is_converged(deleted, "absent", None)
    assert not policy.is_converged(deleted, "present", {})


def test_parse_update_without_changes_raises_permanent_error() -> None:
    with pytest.raises(PermanentMessageError):
        GroupPolicy().parse(
            "update",
            {
                "operationId": "01950000-0000-7000-8000-000000000003",
                "requestDigest": DIGEST,
                "resourceVersion": "1",
            },
        )


def test_parse_rejects_an_unsupported_operation() -> None:
    with pytest.raises(PermanentMessageError):
        GroupPolicy().parse("archive", {})
