from dataclasses import dataclass

from sum_service.observer.domain.authorization import Authorization, ProviderError
from sum_service.observer.domain.observation import Drivers, observe

CATALOG = {"ipm": ("ipm.organization.get", "ipm.organization.list")}


@dataclass
class FakeReader:
    exists: bool = True
    authorizations_found: list[Authorization] | None = None
    fail: bool = False

    async def user_exists(self, user_id: str) -> bool:
        if self.fail:
            raise ProviderError("HTTP 503")
        return self.exists

    async def authorizations(self, user_id: str) -> list[Authorization]:
        return self.authorizations_found or []


def both(fake: FakeReader) -> Drivers:
    """O mesmo fake atende aos dois drivers de leitura (usuário e autorização)."""
    return Drivers(users=fake, authorizations=fake)


async def test_the_observed_roles_are_only_the_service_roles() -> None:
    reader = FakeReader(
        authorizations_found=[
            Authorization("proj-ipm", frozenset({"ipm.organization.get", "ipm.outro.x"})),
        ]
    )
    observation = await observe(both(reader), "u-1", "ipm", CATALOG)
    assert (observation.presence, observation.data) == (
        "present",
        {"serviceRoles": ["ipm.organization.get"]},
    )


async def test_a_user_without_the_roles_is_present_with_none() -> None:
    observation = await observe(both(FakeReader()), "u-1", "ipm", CATALOG)
    assert (observation.presence, observation.data) == ("present", {"serviceRoles": []})


async def test_a_confirmed_missing_user_is_absent() -> None:
    observation = await observe(both(FakeReader(exists=False)), "u-1", "ipm", CATALOG)
    assert (observation.presence, observation.data) == ("absent", {"serviceRoles": []})


async def test_a_read_failure_is_unknown_never_absent() -> None:
    observation = await observe(both(FakeReader(fail=True)), "u-1", "ipm", CATALOG)
    assert (observation.presence, observation.data) == ("unknown", {})


async def test_a_service_outside_the_catalog_observes_no_roles() -> None:
    reader = FakeReader(
        authorizations_found=[Authorization("proj-ipm", frozenset({"ipm.organization.get"}))]
    )
    observation = await observe(both(reader), "u-1", "sum", CATALOG)
    assert observation.data == {"serviceRoles": []}
