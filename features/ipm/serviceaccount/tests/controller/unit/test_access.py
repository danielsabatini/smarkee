"""Permissões efetivas e índice de pertencimento do Controller (decisão 0097)."""

from ipm_serviceaccount.common.catalog import AccessCatalog
from ipm_serviceaccount.controller.domain.access import MembershipIndex, effective_permissions


def test_effective_permissions_expand_the_roles() -> None:
    catalog = AccessCatalog(
        grantable_permissions=["ipm.serviceaccount.get", "ipm.serviceaccount.list"],
        roles={"ipm.saViewer": ["ipm.serviceaccount.get"]},
    )
    desired = {"lifecycle": "present", "organizationId": "org-1", "roles": ["ipm.saViewer"]}

    assert effective_permissions(catalog, desired) == {"ipm.serviceaccount.get"}


def test_an_absent_serviceaccount_has_no_effective_permissions() -> None:
    desired = {"lifecycle": "absent", "organizationId": "org-1", "roles": ["ipm.userViewer"]}

    assert effective_permissions(AccessCatalog(), desired) == frozenset()


def test_the_legacy_permissions_field_of_the_desired_is_ignored() -> None:
    desired = {"lifecycle": "present", "organizationId": "org-1", "permissions": ["ipm.user.bind"]}

    assert effective_permissions(AccessCatalog(), desired) == frozenset()


def test_the_index_finds_who_has_a_role() -> None:
    index = MembershipIndex()
    index.apply("a", {"organizationId": "org-1", "roles": ["ipm.userViewer"]})
    index.apply("b", {"organizationId": "org-1", "roles": ["ipm.userAdmin"]})
    index.apply("c", {"organizationId": "org-1"})

    assert index.with_role("ipm.userViewer") == {"a"}
    assert index.with_any_access() == {"a", "b"}
