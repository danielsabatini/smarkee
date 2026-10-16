"""Limpeza de dev: o que é de teste (e só isso), a ordem de remoção e a verificação final."""

from dataclasses import dataclass, field

import pytest

from smarkee_dev_cleanup.engine import (
    apply,
    clean,
    find,
    is_test_organization,
    is_test_user,
    remove_through_the_loop,
)
from smarkee_dev_cleanup.main import refuse_outside_development
from smarkee_dev_cleanup.model import (
    ACCOUNTS,
    ORGANIZATIONS,
    SERVICES,
    Findings,
    Kind,
    Ports,
    Row,
)

ORG_ID = "01a14454-81be-7100-a313-2e3729712ddc"
USER_ID = "01a1447d-fb81-76eb-a932-b97cc46a1153"
REAL_USER = "01a1447d-0000-7000-8000-00000000beef"


@dataclass
class FakeIdentity:
    orgs: dict[str, str] = field(default_factory=lambda: {})
    users: dict[str, str] = field(default_factory=lambda: {})
    deleted: list[str] = field(default_factory=lambda: [])

    def organizations(self) -> dict[str, str]:
        return dict(self.orgs)

    def register_users(self) -> dict[str, str]:
        return dict(self.users)

    def delete_organization(self, organization_id: str) -> None:
        self.deleted.append(f"org:{organization_id}")
        self.orgs.pop(organization_id, None)

    def delete_user(self, user_id: str) -> None:
        self.deleted.append(f"user:{user_id}")
        self.users.pop(user_id, None)


@dataclass
class FakeSsot:
    tables: dict[Kind, list[Row]] = field(default_factory=lambda: {})
    deleted: list[tuple[str, set[str]]] = field(default_factory=lambda: [])
    never_unprotects: bool = False

    def rows(self, kind: Kind) -> list[Row]:
        return list(self.tables.get(kind, []))

    def unprotected_version(self, kind: Kind, resource_id: str) -> str | None:
        return None if self.never_unprotects else "3"

    def delete(self, kind: Kind, resource_ids: set[str]) -> None:
        self.deleted.append((kind.table, set(resource_ids)))
        self.tables[kind] = [
            r for r in self.tables.get(kind, []) if r.resource_id not in resource_ids
        ]


@dataclass
class FakeBus:
    phases: dict[str, str] = field(default_factory=lambda: {})
    removes_when_asked: bool = True
    requested: list[str] = field(default_factory=lambda: [])
    unprotection_requested: list[str] = field(default_factory=lambda: [])
    purged: dict[str, set[str]] = field(default_factory=lambda: {})
    gone: set[str] = field(default_factory=lambda: set())

    async def last_version(self, kind: Kind, resource_id: str) -> tuple[str, str] | None:
        phase = self.phases.get(resource_id)
        return (phase, "3") if phase else None

    async def request_unprotection(self, kind: Kind, resource_id: str, version: str) -> None:
        assert version == "3"
        self.unprotection_requested.append(resource_id)

    async def request_deletion(self, kind: Kind, resource_id: str, version: str) -> None:
        self.requested.append(resource_id)
        assert version == "3"
        if self.removes_when_asked:
            self.gone.add(resource_id)

    async def removed(self, kind: Kind, resource_id: str) -> bool:
        return resource_id in self.gone

    async def purge(self, kind: Kind, resource_ids: set[str]) -> None:
        self.purged.setdefault(kind.module, set()).update(resource_ids)


@dataclass
class FakeMail:
    messages: int = 0

    def count(self) -> int:
        return self.messages

    def delete(self) -> None:
        self.messages = 0


@dataclass
class World:
    identity: FakeIdentity = field(default_factory=FakeIdentity)
    ssot: FakeSsot = field(default_factory=FakeSsot)
    bus: FakeBus = field(default_factory=FakeBus)
    mail: FakeMail = field(default_factory=FakeMail)
    ticks: list[float] = field(default_factory=lambda: [0.0])

    def ports(self) -> Ports:
        async def sleep(seconds: float) -> None:
            self.ticks.append(self.ticks[-1] + seconds)

        return Ports(self.identity, self.ssot, self.bus, self.mail, sleep, lambda: self.ticks[-1])


def say_nothing(_: str) -> None:
    return None


# ---------------------------------------------------------------------- o que é de teste


@pytest.mark.parametrize(
    "name", ["conf-ab12", "acme-1", "loop-x-b", "dup-1", "chaos-manager-1", "e2e-9", "probe-1"]
)
def test_an_organization_with_a_test_name_and_a_uuid_is_test_data(name: str) -> None:
    assert is_test_organization(ORG_ID, name)


@pytest.mark.parametrize(
    ("organization_id", "name"),
    [
        ("394341608402780164", "acme-corp"),  # ID do Zitadel, e não o `resourceId` de um recurso
        (ORG_ID, "acme"),  # sem o hífen do padrão
        (ORG_ID, "minha-empresa"),
        (ORG_ID, "core"),
        (ORG_ID, "register"),
        (ORG_ID, "smarkee"),
    ],
)
def test_real_or_system_organizations_are_never_test_data(organization_id: str, name: str) -> None:
    assert not is_test_organization(organization_id, name)


@pytest.mark.parametrize(
    "email",
    [
        "e2e-6a67549d@example.com",
        "loop.ab12cd34ef@example.com",
        "conf.ab12@example.com",
        "chaos.manager.1234abcd@example.com",
        "cons.ab12@example.com",
        "sa.test.ab12cd34@example.com",
    ],
)
def test_a_test_email_is_recognized(email: str) -> None:
    assert is_test_user(email)


@pytest.mark.parametrize(
    "email",
    [
        "ana@example.com",
        "e2e-6a67549d@empresa.com.br",  # só `example.com` é de teste
        "daniel@smarkee.internal",
        "e2e@example.com",  # sem o separador depois do rótulo
        "",
    ],
)
def test_a_real_email_is_never_test_data(email: str) -> None:
    assert not is_test_user(email)


def test_find_picks_only_test_resources() -> None:
    world = World()
    world.identity.orgs = {
        "394341608402780164": "smarkee",
        "395132726044262411": "register",
        ORG_ID: "acme-d5d03b3d9c",
        "01a14454-0000-7000-8000-000000000001": "minha-empresa",
    }
    world.identity.users = {USER_ID: "e2e-6a67549d@example.com", REAL_USER: "ana@example.com"}
    world.ssot.tables = {
        ACCOUNTS: [Row(USER_ID, "e2e-6a67549d@example.com"), Row(REAL_USER, "ana@example.com")],
        ORGANIZATIONS: [Row(ORG_ID, "acme-d5d03b3d9c"), Row("outra", "minha-empresa")],
        SERVICES: [Row("s1", USER_ID), Row("s2", REAL_USER)],
    }

    findings = find(world.ports())

    assert set(findings.zitadel_users) == {USER_ID}
    assert set(findings.zitadel_organizations) == {ORG_ID}
    assert [r.resource_id for r in findings.account_rows] == [USER_ID]
    assert [r.resource_id for r in findings.organization_rows] == [ORG_ID]
    assert [r.resource_id for r in findings.service_rows] == ["s1"]  # a de ana não é tocada


def test_a_service_link_whose_owner_no_longer_exists_is_an_orphan() -> None:
    world = World()
    world.identity.users = {REAL_USER: "ana@example.com"}
    world.ssot.tables = {SERVICES: [Row("s1", "dono-removido"), Row("s2", REAL_USER)]}

    findings = find(world.ports())

    assert [r.resource_id for r in findings.service_rows] == ["s1"]


def test_a_clean_environment_has_no_findings() -> None:
    assert find(World().ports()).is_clean()


# ---------------------------------------------------------------------- relatório


async def test_without_apply_it_only_reports_and_exits_1() -> None:
    world = World()
    world.identity.orgs = {ORG_ID: "acme-1"}
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=False, say=lines.append)

    assert code == 1
    assert world.identity.deleted == [] and world.bus.requested == []
    assert any("acme-1" in line for line in lines) and any("--apply" in line for line in lines)


async def test_a_clean_environment_exits_0() -> None:
    assert await clean(World().ports(), apply_changes=True, say=say_nothing) == 0


# ---------------------------------------------------------------------- remover


async def test_the_loop_is_tried_first_and_only_ready_resources_are_asked() -> None:
    world = World()
    world.bus.phases = {ORG_ID: "Ready", USER_ID: "Failed"}

    ready = await remove_through_the_loop(world.ports(), ORGANIZATIONS, ORG_ID, say_nothing)
    failed = await remove_through_the_loop(world.ports(), ACCOUNTS, USER_ID, say_nothing)

    assert ready is True and failed is False
    assert world.bus.requested == [ORG_ID]  # o que não está `Ready` não é pedido ao loop


async def test_a_resource_the_loop_does_not_remove_in_time_is_reported_as_not_removed() -> None:
    world = World()
    world.bus.phases = {ORG_ID: "Ready"}
    world.bus.removes_when_asked = False

    assert await remove_through_the_loop(world.ports(), ORGANIZATIONS, ORG_ID, say_nothing) is False


async def test_apply_removes_through_the_loop_then_directly_what_is_left_and_verifies() -> None:
    world = World()
    world.identity.orgs = {ORG_ID: "acme-1"}
    world.identity.users = {USER_ID: "e2e-1@example.com"}
    world.ssot.tables = {
        ORGANIZATIONS: [Row(ORG_ID, "acme-1")],
        ACCOUNTS: [Row(USER_ID, "e2e-1@example.com")],
        SERVICES: [Row("s1", USER_ID)],
    }
    world.bus.phases = {ORG_ID: "Ready"}  # a organização sai pelo loop; o usuário, direto
    world.mail.messages = 2

    class LoopRemoves(FakeBus):
        async def request_deletion(self, kind: Kind, resource_id: str, version: str) -> None:
            await super().request_deletion(kind, resource_id, version)
            world.identity.orgs.pop(resource_id, None)  # o Executor remove no Zitadel
            world.ssot.tables[ORGANIZATIONS] = []  # e o Manager apaga a linha

    loop = LoopRemoves(phases=world.bus.phases)
    world.bus = loop
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=True, say=lines.append)

    assert code == 0, lines
    assert loop.requested == [ORG_ID]
    assert world.identity.deleted == [f"user:{USER_ID}"]  # só o que o loop não removeu
    assert find(world.ports()).is_clean()
    assert loop.purged["ipm"] == {ORG_ID}
    assert loop.purged["core"] == {USER_ID} and loop.purged["sum"] == {"s1"}
    assert world.mail.messages == 0


async def test_apply_exits_1_when_something_survives() -> None:
    class Stubborn(FakeIdentity):
        def delete_organization(self, organization_id: str) -> None:
            self.deleted.append(f"org:{organization_id}")  # o Zitadel "aceitou" e não removeu

    world = World(identity=Stubborn(orgs={ORG_ID: "acme-1"}))
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=True, say=lines.append)

    assert code == 1
    assert any("Ainda sobrou" in line for line in lines)


async def test_apply_never_touches_real_data() -> None:
    world = World()
    world.identity.users = {REAL_USER: "ana@example.com"}
    world.identity.orgs = {ORG_ID: "minha-empresa"}
    world.ssot.tables = {ACCOUNTS: [Row(REAL_USER, "ana@example.com")]}

    findings = find(world.ports())
    await apply(world.ports(), findings, say_nothing)

    assert world.identity.deleted == [] and world.ssot.deleted == []
    assert world.bus.requested == [] and world.bus.purged == {}


# ---------------------------------------------------------------------- recusar fora de dev


@pytest.mark.parametrize(
    "variable",
    ["CLEANUP_ZITADEL_URL", "CLEANUP_DATABASE_HOST", "CLEANUP_NATS_URL", "CLEANUP_MAIL_URL"],
)
def test_it_refuses_to_run_against_another_environment(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "https://prd.exemplo")

    with pytest.raises(SystemExit, match=variable):
        refuse_outside_development()


def test_findings_list_everything_it_would_remove() -> None:
    findings = Findings(zitadel_users={USER_ID: "e2e-1@example.com"}, mails=3)

    text = "\n".join(findings.lines())

    assert USER_ID in text and "3 mensagem" in text


async def test_a_protected_resource_is_unprotected_before_the_loop_deletes_it() -> None:
    world = World()
    world.ssot.tables[ORGANIZATIONS] = [Row(ORG_ID, "conf-1")]
    world.identity.orgs[ORG_ID] = "conf-1"
    world.bus.phases[ORG_ID] = "Ready"
    lines: list[str] = []

    await clean(world.ports(), apply_changes=True, say=lines.append)

    assert world.bus.unprotection_requested == [ORG_ID]
    assert world.bus.requested == [ORG_ID]


async def test_without_unprotection_the_loop_is_skipped_and_the_direct_path_is_used() -> None:
    world = World()
    world.ssot.never_unprotects = True
    world.ssot.tables[ORGANIZATIONS] = [Row(ORG_ID, "conf-1")]
    world.identity.orgs[ORG_ID] = "conf-1"
    world.bus.phases[ORG_ID] = "Ready"

    await clean(world.ports(), apply_changes=True, say=say_nothing)

    assert world.bus.requested == []  # o delete nunca foi pedido ao loop
    assert world.identity.deleted == [f"org:{ORG_ID}"]
