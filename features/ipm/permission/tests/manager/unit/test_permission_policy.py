"""Testes unitários da política de domínio do Manager de `ipm.permission` (decisão 0083)."""

from ipm_permission.manager.domain.permission import PermissionPolicy
from ipm_permission.manager.domain.policy import Request


def test_desired_for_create_sets_defaults() -> None:
    policy = PermissionPolicy()
    req = Request(
        operation="create",
        operation_id="01950000-0000-7000-8000-000000000001",
        request_digest="a" * 64,
        specification={
            "name": "ipm.user.bind",
            "description": "Atribuir e alterar permissões.",
            "grantable": True,
        },
    )
    desired = policy.desired_for_create(req, "operator-1")
    assert desired == {
        "lifecycle": "present",
        "name": "ipm.user.bind",
        "description": "Atribuir e alterar permissões.",
        "grantable": True,
        "deletionProtection": True,
    }


def test_desired_for_update_keeps_immutable_name() -> None:
    policy = PermissionPolicy()
    current = {
        "lifecycle": "present",
        "name": "ipm.user.bind",
        "description": "Antiga.",
        "grantable": True,
        "deletionProtection": True,
    }
    req = Request(
        operation="update",
        operation_id="01950000-0000-7000-8000-000000000002",
        request_digest="b" * 64,
        resource_version=1,
        specification={
            "description": "Nova descrição.",
            "grantable": False,
            "deletionProtection": False,
        },
    )
    desired = policy.desired_for_update(current, req)
    assert desired["name"] == "ipm.user.bind"
    assert desired["description"] == "Nova descrição."
    assert desired["grantable"] is False
    assert desired["deletionProtection"] is False


def test_is_converged_checks_name_description_and_module_group() -> None:
    policy = PermissionPolicy()
    desired = {
        "lifecycle": "present",
        "name": "ipm.user.bind",
        "description": "Atribuir e alterar permissões.",
        "grantable": True,
    }
    observed_ok = {
        "name": "ipm.user.bind",
        "description": "Atribuir e alterar permissões.",
        "group": "ipm",
    }
    assert policy.is_converged(desired, "present", observed_ok) is True
    assert policy.is_converged(desired, "present", {**observed_ok, "group": "bsm"}) is False
    assert policy.is_converged(desired, "absent", None) is False
    assert policy.is_converged({"lifecycle": "absent"}, "absent", None) is True
