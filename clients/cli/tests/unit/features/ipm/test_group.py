"""Cliente do `ipm.group`: validações e leitura estrita das respostas."""

from typing import Any

import pytest

from sk.features.ipm.group import (
    _group,  # pyright: ignore[reportPrivateUsage]
    validate_description,
    validate_group_name,
    validate_roles_list,
)
from sk.http import ApiUnavailableError


def test_group_name_validation() -> None:
    assert validate_group_name("devops") == "devops"
    assert validate_group_name("sre-team") == "sre-team"
    for invalid in ("Devops", "a", "slug_underscore", "-start", "end-"):
        with pytest.raises(ValueError, match="group name invalid"):
            validate_group_name(invalid)


def test_group_description_validation() -> None:
    assert validate_description("Time de DevOps") == "Time de DevOps"
    with pytest.raises(ValueError, match="between 1 and 256 characters"):
        validate_description("")
    with pytest.raises(ValueError, match="explain the group"):
        validate_description("devops", name="devops")


def test_group_roles_list_validation() -> None:
    assert validate_roles_list(["ipm.userViewer", "ipm.groupViewer", "ipm.userViewer"]) == [
        "ipm.groupViewer",
        "ipm.userViewer",
    ]
    with pytest.raises(ValueError, match="role invalid"):
        validate_roles_list(["invalid_role"])


def test_group_document_parsing() -> None:
    raw: dict[str, Any] = {
        "resourceId": "g-1",
        "resourceVersion": "2",
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "organizationId": "org-1",
            "specification": {
                "name": "devops",
                "description": "Equipe de operações",
                "roles": ["ipm.userViewer"],
                "deletionProtection": True,
                "status": "active",
            },
        },
    }
    group = _group(raw)  # pyright: ignore[reportPrivateUsage]
    assert group.resource_id == "g-1"
    assert group.organization_id == "org-1"
    assert group.name == "devops"
    assert group.roles == ("ipm.userViewer",)
    assert group.deletion_protection is True


def test_group_missing_fields_raises() -> None:
    raw: dict[str, Any] = {
        "resourceId": "g-1",
        "resourceVersion": "1",
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "organizationId": "org-1",
            "specification": {"description": "desc"},
        },
    }
    with pytest.raises(ApiUnavailableError):
        _group(raw)  # pyright: ignore[reportPrivateUsage]
