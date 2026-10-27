"""Permissões efetivas e índice de pertencimento do Controller (decisão 0097)."""

from ipm_user.common.catalog import AccessCatalog
from ipm_user.controller.domain.access import MembershipIndex, effective_permissions


def test_effective_permissions_join_direct_roles_and_group_roles() -> None:
    catalog = AccessCatalog(
        grantable_permissions=["ipm.user.get", "ipm.user.list", "ipm.group.get"],
        roles={"ipm.userViewer": ["ipm.user.get"], "ipm.groupViewer": ["ipm.group.get"]},
        groups={("org-1", "devs"): ["ipm.groupViewer"]},
    )
    desired = {
        "lifecycle": "present",
        "organizationId": "org-1",
        "roles": ["ipm.userViewer"],
        "groups": ["devs"],
    }

    assert effective_permissions(catalog, desired) == {"ipm.user.get", "ipm.group.get"}


def test_a_group_of_another_organization_grants_nothing() -> None:
    catalog = AccessCatalog(
        grantable_permissions=["ipm.group.get"],
        roles={"ipm.groupViewer": ["ipm.group.get"]},
        groups={("org-2", "devs"): ["ipm.groupViewer"]},
    )
    desired = {"lifecycle": "present", "organizationId": "org-1", "groups": ["devs"]}

    assert effective_permissions(catalog, desired) == frozenset()


def test_an_absent_user_has_no_effective_permissions() -> None:
    desired = {"lifecycle": "absent", "organizationId": "org-1", "roles": ["ipm.userViewer"]}

    assert effective_permissions(AccessCatalog(), desired) == frozenset()


def test_the_legacy_permissions_field_of_the_desired_is_ignored() -> None:
    desired = {"lifecycle": "present", "organizationId": "org-1", "permissions": ["ipm.user.bind"]}

    assert effective_permissions(AccessCatalog(), desired) == frozenset()


def test_the_index_finds_who_has_a_role_directly_or_by_group() -> None:
    catalog = AccessCatalog(
        roles={"ipm.userViewer": ["ipm.user.get"]}, groups={("org-1", "devs"): ["ipm.userViewer"]}
    )
    index = MembershipIndex()
    index.apply("direct", {"organizationId": "org-1", "roles": ["ipm.userViewer"]})
    index.apply("by-group", {"organizationId": "org-1", "groups": ["devs"]})
    index.apply("other-org", {"organizationId": "org-2", "groups": ["devs"]})
    index.apply("none", {"organizationId": "org-1"})

    assert index.with_role("ipm.userViewer", catalog) == {"direct", "by-group"}
    assert index.in_group("org-1", "devs") == {"by-group"}
    assert index.with_any_access() == {"direct", "by-group", "other-org"}
