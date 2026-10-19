"""Mapeamento do Zitadel para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

from ipm_organization.observer.domain.identity import IdentityOrganization, ProviderError
from ipm_organization.observer.domain.observation import observe


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


def organization(state: str = "ORGANIZATION_STATE_ACTIVE") -> IdentityOrganization:
    return IdentityOrganization("acme", state)


async def test_absent_organization() -> None:
    result = await observe(FakeReader(None), "o-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_an_active_organization_is_granted() -> None:
    result = await observe(FakeReader(organization()), "o-1")
    assert result.presence == "present"
    assert result.data == {
        "name": "acme",
        "platformAccess": "granted",
        "organizationState": "active",
    }


async def test_an_inactive_organization_is_revoked() -> None:
    result = await observe(FakeReader(organization("ORGANIZATION_STATE_INACTIVE")), "o-1")
    assert result.data == {
        "name": "acme",
        "platformAccess": "revoked",
        "organizationState": "inactive",
    }


async def test_a_state_the_contract_does_not_know_is_unknown() -> None:
    for state in ("ORGANIZATION_STATE_UNSPECIFIED", "ORGANIZATION_STATE_REMOVED", ""):
        result = await observe(FakeReader(organization(state)), "o-1")
        assert (result.presence, result.data) == ("unknown", {})


async def test_read_failures_are_unknown() -> None:
    result = await observe(FakeReader(None, error=ProviderError("HTTP 503")), "o-1")
    assert (result.presence, result.data) == ("unknown", {})
