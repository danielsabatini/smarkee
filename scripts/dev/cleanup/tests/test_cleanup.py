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
    BILLING_ACCOUNTS,
    GROUPS,
    ORGANIZATION_USERS,
    ORGANIZATIONS,
    ROLES,
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
    platform: dict[Kind, list[Row]] = field(default_factory=lambda: {})
    """Linhas do plano de dados (banco `platform`) por tipo."""
    never_unprotects: bool = False
    support: dict[Kind, list[Row]] = field(default_factory=lambda: {})
    """Histórico (outbox, Operations e resultados) por tipo, com o rótulo do outbox."""

    def rows(self, kind: Kind) -> list[Row]:
        return list(self.tables.get(kind, []))

    def data_plane_rows(self, kind: Kind) -> list[Row]:
        return list(self.platform.get(kind, []))

    def delete_data_plane(self, kind: Kind, resource_ids: set[str]) -> None:
        self.deleted.append((f"platform:{kind.table}", set(resource_ids)))
        self.platform[kind] = [
            r for r in self.platform.get(kind, []) if r.resource_id not in resource_ids
        ]

    def unprotected_version(self, kind: Kind, resource_id: str) -> str | None:
        return None if self.never_unprotects else "3"

    def history(self, kind: Kind) -> list[Row]:
        return list(self.support.get(kind, []))

    def delete(self, kind: Kind, resource_ids: set[str]) -> None:
        self.deleted.append((kind.table, set(resource_ids)))
        self.tables[kind] = [
            r for r in self.tables.get(kind, []) if r.resource_id not in resource_ids
        ]
        self.support[kind] = [
            r for r in self.support.get(kind, []) if r.resource_id not in resource_ids
        ]


@dataclass
class FakeBus:
    phases: dict[str, str] = field(default_factory=lambda: {})
    removes_when_asked: bool = True
    requested: list[str] = field(default_factory=lambda: [])
    unprotection_requested: list[str] = field(default_factory=lambda: [])
    purged: dict[str, set[str]] = field(default_factory=lambda: {})
    gone: set[str] = field(default_factory=lambda: set())
    messages: dict[str, set[str]] = field(default_factory=lambda: {})
    """`resourceId` com mensagens nos Streams, por módulo."""

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
        self.messages.get(kind.module, set()).difference_update(resource_ids)

    async def orphan_messages(self, live: dict[Kind, set[str]]) -> dict[Kind, set[str]]:
        return {kind: self.messages.get(kind.module, set()) - ids for kind, ids in live.items()}


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
    "name",
    [
        "conf-ab12",
        "acme-1",
        "loop-x-b",
        "dup-1",
        "chaos-manager-1",
        "e2e-9",
        "probe-1",
        "org-0c6eef4158",
        "renamed-e0a3d42379",
    ],
)
def test_an_organization_with_a_test_name_and_a_uuid_is_test_data(name: str) -> None:
    assert is_test_organization(ORG_ID, name)


@pytest.mark.parametrize(
    ("organization_id", "name"),
    [
        ("394341608402780164", "acme-corp"),  # ID do Zitadel, e não o `resourceId` de um recurso
        (ORG_ID, "acme"),  # sem o hífen do padrão
        (ORG_ID, "minha-empresa"),
        (ORG_ID, "org-acme-corp"),  # `org-` sem os 10 hexadecimais do nome de teste
        (ORG_ID, "org-0c6eef41589"),  # hexadecimais a mais
        (ORG_ID, "org-0c6eef415"),  # hexadecimais a menos
        (ORG_ID, "renamed-acme"),  # `renamed-` sem os 10 hexadecimais do nome de teste
        (ORG_ID, "renamed-e0a3d423791"),  # hexadecimais a mais
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
        "ana.d8cf979f97@example.com",  # testes de integração do Manager da Account
        "dup.16a54b90a9@example.com",
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
        "ana.souza@example.com",  # `ana.` só é de teste com 10 hexadecimais
        "ana.d8cf979f9@example.com",  # 9 hexadecimais
        "ana.d8cf979f97x@example.com",
        "dup.16a54b90a9@empresa.com.br",
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
        BILLING_ACCOUNTS: [Row("ba-1", "Acme 0c6eef4158"), Row("ba-2", "Conta Principal")],
        ORGANIZATIONS: [Row(ORG_ID, "acme-d5d03b3d9c"), Row("outra", "minha-empresa")],
        SERVICES: [Row("s1", USER_ID), Row("s2", REAL_USER)],
    }

    findings = find(world.ports())

    assert set(findings.zitadel_users) == {USER_ID}
    assert set(findings.zitadel_organizations) == {ORG_ID}
    assert [r.resource_id for r in findings.account_rows] == [USER_ID]
    assert [r.resource_id for r in findings.billing_account_rows] == ["ba-1"]
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


# ---------------------------------------------------------------------- histórico de removidos


def world_with_history() -> World:
    """Recursos já removidos pelo loop: sem linha principal, só o histórico no SSOT."""
    world = World()
    world.ssot.support = {
        ACCOUNTS: [
            Row("a1", "e2e-1@example.com"),  # de teste
            Row("a2", "ana@example.com"),  # fora do padrão de teste
            Row("a3", ""),  # sem rótulo no outbox: não dá para saber
        ],
        ORGANIZATIONS: [Row("o1", "org-0c6eef4158"), Row("o2", "minha-org")],
        SERVICES: [Row("s1", "a1"), Row("s2", "a2"), Row("s3", "dono-desconhecido")],
        ORGANIZATION_USERS: [Row("u1", "loop-1a2b@example.com"), Row("u2", "bia@empresa.com")],
    }
    return world


def test_history_of_removed_test_resources_is_found_and_the_rest_is_kept() -> None:
    findings = find(world_with_history().ports())

    assert {
        k.resource_type: [r.resource_id for r in rows] for k, rows in findings.history.items()
    } == {
        "account": ["a1"],
        "organization": ["o1"],
        "service": ["s1"],  # a ligação do dono de teste; a do dono real e a sem dono ficam
        "user": ["u1"],  # usuário da Organization: de teste pelo e-mail, como a conta
    }
    assert findings.kept_history == {
        ACCOUNTS: 2,
        BILLING_ACCOUNTS: 0,
        ORGANIZATIONS: 1,
        SERVICES: 2,
        ORGANIZATION_USERS: 1,
        ROLES: 0,
        GROUPS: 0,
    }
    assert not findings.is_clean()
    assert any("histórico" in line for line in findings.lines())


def test_a_resource_that_still_has_a_main_row_is_not_history() -> None:
    world = world_with_history()
    world.ssot.tables = {ACCOUNTS: [Row("a1", "e2e-1@example.com")]}

    findings = find(world.ports())

    assert ACCOUNTS not in findings.history  # ainda existe: é resíduo vivo, não histórico
    assert [r.resource_id for r in findings.account_rows] == ["a1"]


async def test_apply_purges_the_history_and_the_messages_of_test_resources_only() -> None:
    world = world_with_history()
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=True, say=lines.append)

    assert code == 0, lines
    assert world.bus.purged == {"core": {"a1"}, "ipm": {"o1", "u1"}, "sum": {"s1"}}
    remaining = {
        k.resource_type: [r.resource_id for r in rows] for k, rows in world.ssot.support.items()
    }
    assert remaining == {
        "account": ["a2", "a3"],
        "organization": ["o2"],
        "service": ["s2", "s3"],
        "user": ["u2"],
    }
    assert any("Histórico mantido" in line and "2 de core.account" in line for line in lines)


async def test_a_clean_environment_still_mentions_the_history_it_kept() -> None:
    world = world_with_history()
    await clean(world.ports(), apply_changes=True, say=say_nothing)
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=False, say=lines.append)

    assert code == 0  # o histórico mantido não é resíduo de teste
    assert lines[0].startswith("Ambiente limpo")
    assert any(line.startswith("Histórico mantido") for line in lines)


async def test_orphans_mode_removes_all_history_and_orphan_messages_but_not_live_ones() -> None:
    world = world_with_history()
    world.ssot.tables = {ACCOUNTS: [Row("viva", "ana@example.com")]}
    world.bus.messages = {"core": {"viva", "a2", "so-nats"}}
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=True, orphans=True, say=lines.append)

    assert code == 0, lines
    assert world.ssot.support == {
        ACCOUNTS: [],
        ORGANIZATIONS: [],
        SERVICES: [],
        ORGANIZATION_USERS: [],
    }
    assert world.bus.messages == {"core": {"viva"}}
    assert [r.resource_id for r in world.ssot.tables[ACCOUNTS]] == ["viva"]
    assert not any("Histórico mantido" in line for line in lines)


async def test_orphans_mode_without_apply_only_lists() -> None:
    world = world_with_history()
    world.bus.messages = {"core": {"so-nats"}}
    lines: list[str] = []

    code = await clean(world.ports(), apply_changes=False, orphans=True, say=lines.append)

    assert code == 1
    assert any("sem linha principal" in line for line in lines)
    assert world.bus.messages == {"core": {"so-nats"}}


async def test_default_mode_leaves_orphan_messages_alone() -> None:
    world = World()
    world.bus.messages = {"core": {"so-nats"}}

    code = await clean(world.ports(), apply_changes=True, say=say_nothing)

    assert code == 0
    assert world.bus.messages == {"core": {"so-nats"}}


async def test_organization_users_of_test_are_removed_through_the_loop_before_organizations() -> (
    None
):
    """A Organization só é removida vazia (decisão 0077): os usuários dela saem antes."""
    world = World()
    world.ssot.tables = {
        ORGANIZATION_USERS: [Row("u1", "loop-1a2b@example.com"), Row("u2", "bia@empresa.com")],
        ORGANIZATIONS: [Row(ORG_ID, "conf-1")],
    }
    findings = find(world.ports())
    assert [row.resource_id for row in findings.organization_user_rows] == ["u1"]
    assert any("SSOT ipm.user u1" in line for line in findings.lines())
    assert ORGANIZATION_USERS in findings.resource_ids()


ROLE_ID = "01a170c3-7b04-72f3-9c18-2da346a43296"


@pytest.mark.parametrize("name", ["test.role6d7092", "test.chaos0a1b2c"])
def test_a_test_role_is_found_in_the_ssot_and_in_the_platform_database(name: str) -> None:
    world = World()
    world.ssot.tables = {ROLES: [Row(ROLE_ID, name)]}
    world.ssot.platform = {ROLES: [Row(ROLE_ID, name)]}

    findings = find(world.ports())

    assert [row.resource_id for row in findings.role_rows] == [ROLE_ID]
    assert [row.resource_id for row in findings.platform_role_rows] == [ROLE_ID]
    assert any("platform ipm.role" in line for line in findings.lines())
    assert ROLES in findings.resource_ids()


@pytest.mark.parametrize(
    "name", ["ipm.userAdmin", "core.accountViewer", "bsm.accountAdmin", "test.roleok", "minha.role"]
)
def test_predefined_and_real_roles_are_never_test_data(name: str) -> None:
    world = World()
    world.ssot.tables = {ROLES: [Row("role-x", name)]}
    world.ssot.platform = {ROLES: [Row("role-x", name)]}

    assert find(world.ports()).is_clean()


async def test_a_test_role_is_removed_through_the_loop_and_what_is_left_in_the_platform() -> None:
    """O loop remove o estado do `platform`; o que sobra sai direto, só o que é de teste."""
    world = World()
    world.ssot.tables = {
        ROLES: [Row(ROLE_ID, "test.role6d7092"), Row("role-ipm-user-admin", "ipm.userAdmin")]
    }
    world.ssot.platform = {
        ROLES: [Row(ROLE_ID, "test.role6d7092"), Row("role-ipm-user-admin", "ipm.userAdmin")]
    }
    world.bus.phases = {ROLE_ID: "Ready"}

    code = await clean(world.ports(), apply_changes=True, say=say_nothing)

    assert code == 0
    assert world.bus.unprotection_requested == [ROLE_ID]
    assert world.bus.requested == [ROLE_ID]
    assert [r.resource_id for r in world.ssot.platform[ROLES]] == ["role-ipm-user-admin"]
    assert [r.resource_id for r in world.ssot.tables[ROLES]] == ["role-ipm-user-admin"]


async def test_a_test_role_only_in_the_platform_database_is_removed_directly() -> None:
    world = World()
    world.ssot.platform = {ROLES: [Row(ROLE_ID, "test.role6d7092")]}

    assert await clean(world.ports(), apply_changes=True, say=say_nothing) == 0
    assert world.ssot.platform[ROLES] == []


GROUP_ID = "01a170c3-7b04-72f3-9c18-2da346a49999"


@pytest.mark.parametrize("name", ["test-group-6d7092", "test-loop-0a1b2c3d", "test-chaos-abcdef"])
def test_a_test_group_is_found_in_the_ssot_and_in_the_platform_database(name: str) -> None:
    world = World()
    world.ssot.tables = {GROUPS: [Row(GROUP_ID, name)]}
    world.ssot.platform = {GROUPS: [Row(GROUP_ID, name)]}

    findings = find(world.ports())

    assert [row.resource_id for row in findings.group_rows] == [GROUP_ID]
    assert [row.resource_id for row in findings.platform_group_rows] == [GROUP_ID]
    assert any("platform ipm.group" in line for line in findings.lines())
    assert GROUPS in findings.resource_ids()


@pytest.mark.parametrize("name", ["auditors", "finance", "test-group-ok", "devops-team"])
def test_real_groups_are_never_test_data(name: str) -> None:
    world = World()
    world.ssot.tables = {GROUPS: [Row("group-x", name)]}
    world.ssot.platform = {GROUPS: [Row("group-x", name)]}

    assert find(world.ports()).is_clean()


async def test_a_test_group_is_removed_through_the_loop_and_what_is_left_in_the_platform() -> None:
    world = World()
    world.ssot.tables = {
        GROUPS: [Row(GROUP_ID, "test-group-6d7092"), Row("group-real", "auditors")]
    }
    world.ssot.platform = {
        GROUPS: [Row(GROUP_ID, "test-group-6d7092"), Row("group-real", "auditors")]
    }
    world.bus.phases = {GROUP_ID: "Ready"}

    code = await clean(world.ports(), apply_changes=True, say=say_nothing)

    assert code == 0
    assert world.bus.unprotection_requested == [GROUP_ID]
    assert world.bus.requested == [GROUP_ID]
    assert [r.resource_id for r in world.ssot.platform[GROUPS]] == ["group-real"]
    assert [r.resource_id for r in world.ssot.tables[GROUPS]] == ["group-real"]

