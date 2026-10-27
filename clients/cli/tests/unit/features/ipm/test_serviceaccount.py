"""Testes do cliente da API de `ipm/serviceaccount` (sk.features.ipm.serviceaccount)."""

import pytest

from sk.features.ipm.serviceaccount import (
    _serviceaccount,  # pyright: ignore[reportPrivateUsage]
    validate_name,
    validate_roles,
)


def test_validate_name() -> None:
    assert validate_name("ci-deployer") == "ci-deployer"
    assert validate_name("machine-01") == "machine-01"
    with pytest.raises(ValueError, match="name invalid"):
        validate_name("Invalid_Name")
    with pytest.raises(ValueError, match="name invalid"):
        validate_name("-invalid")
    with pytest.raises(ValueError, match="name invalid"):
        validate_name("a")


def test_validate_roles() -> None:
    assert validate_roles(["ipm.serviceaccountViewer", "ipm.organizationViewer"]) == [
        "ipm.organizationViewer",
        "ipm.serviceaccountViewer",
    ]
    with pytest.raises(ValueError, match="role invalid"):
        validate_roles(["invalid-role-syntax"])


def test_serviceaccount_parser() -> None:
    payload = {
        "resourceId": "019a1234-5678-7000-8000-000000000001",
        "resourceVersion": "1",
        "phase": "Ready",
        "desired": {
            "lifecycle": "active",
            "organizationId": "019a1234-5678-7000-8000-000000000000",
            "name": "ci-deployer",
            "description": "CI agent",
            "roles": ["ipm.serviceaccountViewer"],
            "deletionProtection": True,
            "keys": [
                {
                    "publicKey": "-----BEGIN PUBLIC KEY-----\n...",
                    "expiresAt": "2027-01-01T00:00:00Z",
                    "fingerprint": "abc12345",
                }
            ],
        },
        "observed": {
            "effectivePermissions": ["ipm.serviceaccount.get"],
            "keys": [
                {
                    "keyId": "k-001",
                    "fingerprint": "abc12345",
                    "expiresAt": "2027-01-01T00:00:00Z",
                    "status": "active",
                }
            ],
        },
    }
    sa = _serviceaccount(payload)
    assert sa.resource_id == "019a1234-5678-7000-8000-000000000001"
    assert sa.name == "ci-deployer"
    assert sa.deletion_protection is True
    assert len(sa.keys) == 1
    assert sa.keys[0].key_id == "k-001"
    assert sa.keys[0].status == "active"
