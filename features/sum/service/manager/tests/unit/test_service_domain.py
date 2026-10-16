import pytest

from sum_service_manager.contracts import generated
from sum_service_manager.domain.service import (
    CatalogError,
    ServiceNotAvailableError,
    disable_desired,
    enable_desired,
    parse_catalog,
    roles_of,
)

CATALOG_JSON = (
    '{"ipm": ["ipm.organization.update", "ipm.organization.create", "ipm.organization.get"]}'
)
OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"


def test_the_catalog_is_read_with_sorted_roles() -> None:
    catalog = parse_catalog(CATALOG_JSON)
    assert catalog == {
        "ipm": ("ipm.organization.create", "ipm.organization.get", "ipm.organization.update")
    }


@pytest.mark.parametrize(
    "raw",
    [
        "não é json",
        "[]",
        "{}",
        '{"IPM": ["ipm.organization.get"]}',
        '{"ipm": []}',
        '{"ipm": ["ipm.organization.get", "ipm.organization.get"]}',
        '{"ipm": ["organization.get"]}',
        '{"ipm": ["ipm.organization.*"]}',
    ],
)
def test_an_invalid_catalog_stops_the_component(raw: str) -> None:
    with pytest.raises(CatalogError):
        parse_catalog(raw)


def test_enable_copies_the_catalog_roles_and_validates_against_the_contract() -> None:
    desired = enable_desired(OWNER, "ipm", parse_catalog(CATALOG_JSON))
    assert desired == {
        "lifecycle": "present",
        "reconciliation": "active",
        "ownerAccountId": OWNER,
        "service": "ipm",
        "serviceRoles": [
            "ipm.organization.create",
            "ipm.organization.get",
            "ipm.organization.update",
        ],
    }
    generated.ServiceDesiredData.model_validate(desired)


def test_a_service_outside_the_catalog_is_not_available() -> None:
    catalog = parse_catalog(CATALOG_JSON)
    with pytest.raises(ServiceNotAvailableError):
        enable_desired(OWNER, "sum", catalog)
    with pytest.raises(ServiceNotAvailableError):
        roles_of(catalog, "outro")


def test_disable_keeps_the_link_and_removes_the_roles() -> None:
    enabled = enable_desired(OWNER, "ipm", parse_catalog(CATALOG_JSON))
    disabled = disable_desired(enabled)
    assert disabled["lifecycle"] == "absent"
    assert disabled["serviceRoles"] == []
    assert (disabled["ownerAccountId"], disabled["service"]) == (OWNER, "ipm")
    generated.ServiceDesiredData.model_validate(disabled)


def test_a_document_that_breaks_the_contract_is_never_returned() -> None:
    bad_owner = "NAO VALIDO"
    with pytest.raises(ValueError, match="fora do contrato"):
        enable_desired(bad_owner, "ipm", parse_catalog(CATALOG_JSON))
