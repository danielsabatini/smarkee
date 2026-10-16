from typing import Any

import pytest

from sum_service_manager.contracts import generated
from sum_service_manager.domain.decision import (
    Accepted,
    Link,
    Rejected,
    decide_create,
    decide_delete,
)
from sum_service_manager.domain.service import enable_desired, parse_catalog

CATALOG = parse_catalog('{"ipm": ["ipm.organization.get", "ipm.organization.list"]}')
OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
LINK_ID = "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b"


def active_link(version: str = "2") -> Link:
    return Link(LINK_ID, version, 1, enable_desired(OWNER, "ipm", CATALOG))


def absent_link() -> Link:
    active: dict[str, Any] = enable_desired(OWNER, "ipm", CATALOG)
    absent: dict[str, Any] = {**active, "lifecycle": "absent", "serviceRoles": []}
    return Link(LINK_ID, "3", 2, absent)


def test_create_is_accepted_when_the_service_is_in_the_catalog_and_there_is_no_active_link() -> (
    None
):
    decision = decide_create(
        owner_account_id=OWNER, service="ipm", catalog=CATALOG, active_link=None
    )
    assert isinstance(decision, Accepted)
    generated.ServiceDesiredData.model_validate(decision.desired)


def test_create_for_a_service_outside_the_catalog_is_rejected() -> None:
    decision = decide_create(
        owner_account_id=OWNER, service="sum", catalog=CATALOG, active_link=None
    )
    assert decision == Rejected("service_unavailable")


def test_create_with_an_active_link_is_rejected_and_names_the_existing_one() -> None:
    decision = decide_create(
        owner_account_id=OWNER, service="ipm", catalog=CATALOG, active_link=active_link()
    )
    assert decision == Rejected("already_exists", existing_resource_id=LINK_ID)


def test_create_again_after_a_disable_is_accepted() -> None:
    decision = decide_create(
        owner_account_id=OWNER, service="ipm", catalog=CATALOG, active_link=absent_link()
    )
    assert isinstance(decision, Accepted)


def test_create_on_the_disabled_resource_of_the_same_pair_is_accepted() -> None:
    decision = decide_create(
        owner_account_id=OWNER,
        service="ipm",
        catalog=CATALOG,
        active_link=None,
        existing_link=absent_link(),
    )
    assert isinstance(decision, Accepted)
    assert decision.desired["lifecycle"] == "present"


def test_create_on_an_active_existing_resource_is_already_exists() -> None:
    decision = decide_create(
        owner_account_id=OWNER,
        service="ipm",
        catalog=CATALOG,
        active_link=None,
        existing_link=active_link(),
    )
    assert decision == Rejected("already_exists", existing_resource_id=LINK_ID)


def test_create_on_the_resource_of_another_owner_or_service_is_a_conflict() -> None:
    other_owner = decide_create(
        owner_account_id="0199c8a4-0000-7000-8000-00000000beef",
        service="ipm",
        catalog=CATALOG,
        active_link=None,
        existing_link=absent_link(),
    )
    assert other_owner == Rejected("conflict")
    catalog = {**CATALOG, "ipm2": ("ipm.organization.get",)}
    other_service = decide_create(
        owner_account_id=OWNER,
        service="ipm2",
        catalog=catalog,
        active_link=None,
        existing_link=absent_link(),
    )
    assert other_service == Rejected("conflict")


def test_delete_is_accepted_with_the_current_version_and_removes_the_roles() -> None:
    decision = decide_delete(link=active_link("2"), expected_version="2")
    assert isinstance(decision, Accepted)
    assert decision.desired["lifecycle"] == "absent"
    assert decision.desired["serviceRoles"] == []
    generated.ServiceDesiredData.model_validate(decision.desired)


def test_delete_with_an_outdated_version_is_a_conflict() -> None:
    decision = decide_delete(link=active_link("2"), expected_version="1")
    assert decision == Rejected("conflict")


@pytest.mark.parametrize("link", [None, absent_link()], ids=["sem ligação", "já desligada"])
def test_delete_of_a_missing_or_disabled_link_is_not_found(link: Link | None) -> None:
    assert decide_delete(link=link, expected_version="3") == Rejected("not_found")
