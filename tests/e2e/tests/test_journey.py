"""Jornada completa: login, ligar o `ipm`, a Organization, renovar a sessão e desligar.

Os testes compartilham a mesma pessoa (fixture `person`) e a mesma ligação: cada um depende do
anterior, como os passos de uma pessoa usando a plataforma.
"""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta

import conftest
import pytest
from conftest import Person, Sk

IPM_ROLE = "ipm.organization"


def _project(name: str) -> str:
    """ID do projeto de roles da variável `E2E_<NOME>_PROJECT_ID` (a fixture já a exigiu)."""
    value: str | None = getattr(conftest, f"{name}_PROJECT_ID")
    assert value, f"E2E_{name}_PROJECT_ID não definida"
    return value


@pytest.fixture(scope="module")
def link() -> dict[str, str]:
    """Estado da ligação criada pela jornada (`resourceId` e `operationId`)."""
    return {}


def _identifiers(text: str) -> tuple[str, str]:
    resource = re.search(r"resourceId\s+(\S+)", text)
    operation = re.search(r"operationId\s+(\S+)", text)
    assert resource and operation, text
    return resource.group(1), operation.group(1)


def _state(sk: Sk, link: dict[str, str]) -> str:
    """Saída do `get` da ligação e da Operation mais recentes."""
    done = sk.run(
        *("sum", "service", "get"),
        *("--resource-id", link["resourceId"]),
        *("--operation-id", link["operationId"]),
    )
    assert done.exit_code == 0, done.text
    return done.stdout


def _field(shown: str, name: str) -> str:
    match = re.search(rf"^[│\s]*{name}\s+(.+?)[│\s]*$", shown, re.MULTILINE)
    assert match, f"campo {name} ausente em:\n{shown}"
    return match.group(1)


def test_the_new_person_cannot_use_the_sum_without_a_session(person: Person) -> None:
    done = person.sk.run("sum", "service", "list")
    assert done.exit_code == 1
    assert "sk auth login" in done.stderr


def test_login_through_the_sk_with_the_real_provider(person: Person) -> None:
    done = person.sk.run("auth", "login", timeout=90.0)
    assert done.exit_code == 0, done.text + person.sk.browser_failure()
    who = person.sk.run("auth", "whoami")
    assert who.exit_code == 0, who.text
    assert person.email in who.stdout
    assert person.sk.credentials().get("refreshToken"), "o login deve emitir refresh token"
    # Decisão 0033: uma revogação de role chega ao token em até 15 minutos.
    assert person.sk.token_lifetime_seconds() <= 900, person.sk.token_lifetime_seconds()


def test_a_new_account_already_holds_the_base_roles_of_the_sum(person: Person) -> None:
    """Sem roles `sum.ipm.get`, o Receiver do SUM responderia 403 à listagem."""
    done = person.sk.run("sum", "service", "list")
    assert done.exit_code == 0, done.text
    assert "No services" in done.stdout


def test_enable_wait_converges_and_the_token_already_carries_the_ipm_roles(
    person: Person, link: dict[str, str]
) -> None:
    assert _project("IPM") not in person.sk.token_roles(), "antes de ligar, o token não tem ipm.*"
    done = person.sk.run("sum", "service", "enable", "--service", "ipm", "--wait", timeout=150.0)
    assert done.exit_code == 0, done.text
    link["resourceId"], link["operationId"] = _identifiers(done.stdout)
    assert _field(done.stdout, "state") == "enabled" and _field(done.stdout, "phase") == "Ready"
    assert _field(done.stdout, "session") == "renewed", done.stdout
    shown = _state(person.sk, link)
    assert _field(shown, "operationStatus") == "completed"
    assert IPM_ROLE in _field(shown, "observedRoles")  # roles observadas no Zitadel
    # O que a opção A garante: o token da sessão já reflete a ligação, sem novo login.
    roles = person.sk.token_roles()
    assert roles.get(_project("IPM"), set()) >= {
        f"{IPM_ROLE}.get",
        f"{IPM_ROLE}.create",
    }, roles
    assert {"core.account.get", "core.account.delete"} <= roles[_project("CORE")]
    assert {"sum.ipm.enable", "sum.ipm.get"} <= roles[_project("SUM")]


def test_the_link_is_listed_and_a_second_enable_points_to_it(
    person: Person, link: dict[str, str], links_cleanup: list[str]
) -> None:
    links_cleanup.append(link["resourceId"])
    listed = person.sk.run("sum", "service", "list")
    assert listed.exit_code == 0 and link["resourceId"] in listed.stdout, listed.text
    again = person.sk.run("sum", "service", "enable", "--service", "ipm")
    assert again.exit_code == 1
    assert "This service is already enabled" in again.stderr, again.stderr


def test_the_organization_is_created_renamed_and_deleted_with_the_sk(
    person: Person, link: dict[str, str]
) -> None:
    """Com o `ipm` ligado, o token traz as roles `ipm.organization.*`: o ciclo pela CLI."""
    sk = person.sk
    name = f"e2e-{uuid.uuid4().hex[:10]}"
    renamed = name + "-b"
    assert "No Organizations" in sk.run("ipm", "organization", "list").stdout
    created_id: str | None = None
    try:
        created = sk.run(
            *("ipm", "organization", "create"), *("--name", name), "--wait", timeout=150.0
        )
        assert created.exit_code == 0, created.text
        created_id = _identifiers(created.stdout)[0]
        assert _field(created.stdout, "name") == name
        assert _field(created.stdout, "state") == "active"
        assert _field(created.stdout, "phase") == "Ready"

        shown = sk.run("ipm", "organization", "get", "--resource-id", created_id)
        assert shown.exit_code == 0, shown.text
        assert _field(shown.stdout, "platformAccess") == "granted"
        listed = sk.run("ipm", "organization", "list")
        assert listed.exit_code == 0 and created_id in listed.stdout, listed.text

        # A cota do dono é de uma Organization: o segundo pedido é recusado com a orientação.
        second = sk.run("ipm", "organization", "create", "--name", name + "-2")
        assert second.exit_code == 1, second.text
        assert "Organization limit" in " ".join(second.stderr.split()), second.stderr

        # Exclusão segura (decisão 0040): com uma Organization e o `ipm` habilitado, a conta fica.
        refused = sk.run("account", "delete", "--yes")
        assert refused.exit_code == 1, refused.text
        text = " ".join(refused.stderr.split())
        assert "1 Organization" in text and "sk ipm organization delete" in text, text

        # E o `ipm` não é desabilitado enquanto houver Organizations (o User confia nisso).
        blocked = sk.run("sum", "service", "disable", "--resource-id", link["resourceId"])
        assert blocked.exit_code == 1, blocked.text
        assert "sk ipm organization delete" in " ".join(blocked.stderr.split()), blocked.stderr

        updated = sk.run(
            *("ipm", "organization", "update"),
            *("--resource-id", created_id),
            *("--name", renamed),
            "--wait",
            timeout=150.0,
        )
        assert updated.exit_code == 0, updated.text
        assert _field(updated.stdout, "name") == renamed
        assert _field(updated.stdout, "phase") == "Ready"
    finally:
        if created_id is not None:
            deleted = sk.run(
                *("ipm", "organization", "delete"),
                *("--resource-id", created_id),
                "--wait",
                timeout=150.0,
            )
            assert deleted.exit_code == 0, deleted.text
            assert "removed" in deleted.stdout, deleted.stdout
    gone = sk.run("ipm", "organization", "get", "--resource-id", created_id or "x")
    assert gone.exit_code == 1
    assert "Organization not found" in " ".join(gone.stderr.split()), gone.stderr
    assert "No Organizations" in sk.run("ipm", "organization", "list").stdout


def test_the_sk_renews_an_expired_session_with_the_refresh_token(person: Person) -> None:
    credentials = person.sk.credentials()
    credentials["accessTokenExpiresAt"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    person.sk.credentials_path.write_text(json.dumps(credentials), encoding="utf-8")
    expired_token = credentials["accessToken"]
    done = person.sk.run("sum", "service", "list")
    assert done.exit_code == 0, done.text
    renewed = person.sk.credentials()
    assert renewed["accessToken"] != expired_token
    assert datetime.fromisoformat(renewed["accessTokenExpiresAt"]) > datetime.now(UTC)


def test_disable_wait_converges_and_the_token_drops_the_ipm_roles(
    person: Person, link: dict[str, str]
) -> None:
    done = person.sk.run(
        *("sum", "service", "disable"),
        *("--resource-id", link["resourceId"]),
        "--wait",
        timeout=150.0,
    )
    assert done.exit_code == 0, done.text
    link["operationId"] = _identifiers(done.stdout)[1]
    assert _field(done.stdout, "state") == "disabled" and _field(done.stdout, "phase") == "Ready"
    assert _field(done.stdout, "session") == "renewed", done.stdout
    assert _field(_state(person.sk, link), "observedRoles") == "none"
    # A revogação também chega ao token: sem isso, o Receiver do ipm ainda aceitaria as roles.
    roles = person.sk.token_roles()
    assert _project("IPM") not in roles, roles


def test_a_second_disable_has_nothing_to_do(person: Person, link: dict[str, str]) -> None:
    done = person.sk.run("sum", "service", "disable", "--resource-id", link["resourceId"])
    assert done.exit_code == 0, done.text
    assert "is already disabled" in done.stdout


def test_enabling_again_reuses_the_same_resource_and_the_list_has_one_row(
    person: Person, link: dict[str, str]
) -> None:
    """O recurso é o par usuário + serviço: habilitar de novo não cria uma segunda linha."""
    done = person.sk.run("sum", "service", "enable", "--service", "ipm", "--wait", timeout=150.0)
    assert done.exit_code == 0, done.text
    assert _identifiers(done.stdout)[0] == link["resourceId"], done.stdout
    assert _field(done.stdout, "state") == "enabled" and _field(done.stdout, "phase") == "Ready"
    listed = person.sk.run("sum", "service", "list")
    assert listed.exit_code == 0, listed.text
    assert listed.stdout.count(link["resourceId"]) == 1, listed.stdout
    assert len(re.findall(r"^[│\s]*[0-9a-f]{8}-", listed.stdout, re.MULTILINE)) == 1, listed.stdout
    link["operationId"] = _identifiers(done.stdout)[1]
    # Deixa o serviço desabilitado: a limpeza do teste não apaga uma ligação habilitada.
    off = person.sk.run(
        *("sum", "service", "disable"),
        *("--resource-id", link["resourceId"]),
        "--wait",
        timeout=150.0,
    )
    assert off.exit_code == 0, off.text
    assert _field(off.stdout, "state") == "disabled"


def test_the_refresh_command_renews_the_session_on_demand(person: Person) -> None:
    before = person.sk.credentials()["accessToken"]
    done = person.sk.run("auth", "refresh")
    assert done.exit_code == 0, done.text
    assert person.sk.credentials()["accessToken"] != before


def test_the_account_is_shown_and_then_deleted_with_the_sk(person: Person) -> None:
    """Sem recursos atrelados (a Organization saiu e o `ipm` foi desabilitado), a conta sai."""
    shown = person.sk.run("account", "get")
    assert shown.exit_code == 0, shown.text
    assert person.email in shown.stdout and person.resource_id in shown.stdout
    deleted = person.sk.run("account", "delete", "--yes", "--wait", timeout=150.0)
    assert deleted.exit_code == 0, deleted.text
    assert "Account deleted" in deleted.stdout, deleted.text
    assert not person.sk.credentials_path.exists(), "a sessão local deve ser esquecida"
