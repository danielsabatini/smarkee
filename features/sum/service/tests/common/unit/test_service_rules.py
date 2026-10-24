import pytest

from sum_service.common.contracts import generated
from sum_service.common.service_rules import (
    CatalogError,
    ServiceNotAvailableError,
    disable_desired,
    enable_desired,
    parse_catalog,
    permissions_of,
    rollout_desired,
)

CATALOG_JSON = (
    '{"ipm": ["ipm.organization.update", "ipm.organization.create", "ipm.organization.get"]}'
)
OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"


def test_the_catalog_is_read_with_sorted_permissions() -> None:
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


def test_enable_copies_the_catalog_permissions_and_validates_against_the_contract() -> None:
    desired = enable_desired(OWNER, "ipm", parse_catalog(CATALOG_JSON))
    assert desired == {
        "lifecycle": "present",
        "reconciliation": "active",
        "ownerAccountId": OWNER,
        "service": "ipm",
        "servicePermissions": [
            "ipm.organization.create",
            "ipm.organization.get",
            "ipm.organization.update",
        ],
        "managedPermissions": [
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
        permissions_of(catalog, "outro")


def test_disable_keeps_the_link_and_removes_the_permissions() -> None:
    enabled = enable_desired(OWNER, "ipm", parse_catalog(CATALOG_JSON))
    disabled = disable_desired(enabled, parse_catalog(CATALOG_JSON))
    assert disabled["lifecycle"] == "absent"
    assert disabled["servicePermissions"] == []
    assert disabled["managedPermissions"] == enabled["managedPermissions"]  # o que revogar
    assert (disabled["ownerAccountId"], disabled["service"]) == (OWNER, "ipm")
    generated.ServiceDesiredData.model_validate(disabled)


def test_a_document_that_breaks_the_contract_is_never_returned() -> None:
    bad_owner = "NAO VALIDO"
    with pytest.raises(ValueError, match="fora do contrato"):
        enable_desired(bad_owner, "ipm", parse_catalog(CATALOG_JSON))


def test_the_rollout_follows_the_catalog_and_keeps_controlling_removed_permissions() -> None:
    """Catálogo novo: ganha a permissão nova e segue controlando a que saiu (decisão 0079)."""
    before = enable_desired(OWNER, "ipm", {"ipm": ("ipm.a.get", "ipm.b.get")})
    after = rollout_desired(before, {"ipm": ("ipm.a.get", "ipm.c.get")})
    assert after is not None
    assert after["servicePermissions"] == ["ipm.a.get", "ipm.c.get"]
    assert after["managedPermissions"] == ["ipm.a.get", "ipm.b.get", "ipm.c.get"]  # ipm.b.get sai
    assert rollout_desired(after, {"ipm": ("ipm.a.get", "ipm.c.get")}) is None  # idempotente


def test_the_rollout_completes_an_old_desired_and_keeps_the_reconciliation() -> None:
    old = {
        "lifecycle": "present",
        "reconciliation": "suspended",
        "ownerAccountId": OWNER,
        "service": "ipm",
        "servicePermissions": ["ipm.a.get"],
    }
    after = rollout_desired(old, {"ipm": ("ipm.a.get",)})
    assert after is not None and after["managedPermissions"] == ["ipm.a.get"]
    assert after["reconciliation"] == "suspended"  # o rollout não reativa o que o operador parou


def test_the_rollout_of_a_disabled_link_only_widens_what_to_revoke() -> None:
    disabled = disable_desired(
        enable_desired(OWNER, "ipm", {"ipm": ("ipm.a.get",)}), {"ipm": ("ipm.a.get",)}
    )
    after = rollout_desired(disabled, {"ipm": ("ipm.a.get", "ipm.c.get")})
    assert after is not None
    assert (after["lifecycle"], after["servicePermissions"]) == ("absent", [])
    assert after["managedPermissions"] == ["ipm.a.get", "ipm.c.get"]
    assert rollout_desired(disabled, {"outro": ("x.y.z",)}) is None  # serviço fora do catálogo
