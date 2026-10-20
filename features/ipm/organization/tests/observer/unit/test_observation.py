"""Mapeamento do Zitadel para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

from ipm_organization.observer.domain.identity import IdentityOrganization, ProviderError
from ipm_organization.observer.domain.observation import Drivers, log_identifiers, observe


class FakeReader:
    def __init__(
        self, organization: IdentityOrganization | None, error: ProviderError | None = None
    ) -> None:
        self._organization = organization
        self._error = error

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None:
        if self._error:
            raise self._error
        return self._organization


class FakeMetadata:
    def __init__(self, value: str | None = "true", error: ProviderError | None = None) -> None:
        self._value = value
        self._error = error

    async def get_value(self, owner_id: str, key: str) -> str | None:
        if self._error:
            raise self._error
        return self._value if key == "deletionProtection" else None


def drivers(reader: FakeReader, metadata: FakeMetadata | None = None) -> Drivers:
    return Drivers(organizations=reader, metadata=metadata or FakeMetadata())


def organization(state: str = "ORGANIZATION_STATE_ACTIVE") -> IdentityOrganization:
    return IdentityOrganization("acme", state)


async def test_absent_organization() -> None:
    result = await observe(drivers(FakeReader(None)), "o-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_an_active_organization_is_granted() -> None:
    result = await observe(drivers(FakeReader(organization())), "o-1")
    assert result.presence == "present"
    assert result.data == {
        "name": "acme",
        "platformAccess": "granted",
        "organizationState": "active",
        "deletionProtection": True,
    }


async def test_an_inactive_organization_is_revoked() -> None:
    result = await observe(drivers(FakeReader(organization("ORGANIZATION_STATE_INACTIVE"))), "o-1")
    assert result.data == {
        "name": "acme",
        "platformAccess": "revoked",
        "organizationState": "inactive",
        "deletionProtection": True,
    }


async def test_a_state_the_contract_does_not_know_is_unknown() -> None:
    for state in ("ORGANIZATION_STATE_UNSPECIFIED", "ORGANIZATION_STATE_REMOVED", ""):
        result = await observe(drivers(FakeReader(organization(state))), "o-1")
        assert (result.presence, result.data) == ("unknown", {})


async def test_read_failures_are_unknown() -> None:
    result = await observe(drivers(FakeReader(None, error=ProviderError("HTTP 503"))), "o-1")
    assert (result.presence, result.data) == ("unknown", {})


async def test_deletion_protection_comes_from_the_metadata() -> None:
    """O metadado `deletionProtection` vira o campo do `observed` (decisão 0074)."""
    result = await observe(drivers(FakeReader(organization()), FakeMetadata("false")), "o-1")
    assert result.data["deletionProtection"] is False


async def test_missing_or_unexpected_metadata_is_left_out_as_a_divergence() -> None:
    for value in (None, "yes", ""):
        result = await observe(drivers(FakeReader(organization()), FakeMetadata(value)), "o-1")
        assert result.presence == "present"
        assert "deletionProtection" not in result.data


async def test_a_metadata_read_failure_is_unknown() -> None:
    failing = FakeMetadata(error=ProviderError("HTTP 503"))
    result = await observe(drivers(FakeReader(organization()), failing), "o-1")
    assert (result.presence, result.data) == ("unknown", {})


def test_log_identifiers_of_the_observation() -> None:
    assert log_identifiers("org-1") == {"organization_id": "org-1"}  # é a própria Organization
