"""Jornada completa, em ordem: login, ligar o `ipm`, renovar a sessão, desligar.

Os testes compartilham a mesma pessoa (fixture `person`) e a mesma ligação: cada um depende do
anterior, como os passos de uma pessoa usando a plataforma.
"""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from conftest import Person, Sk, wait_until

IPM_ROLE = "ipm.organization"


@pytest.fixture(scope="module")
def link() -> dict[str, str]:
    """Estado da ligação criada pela jornada (`resourceId` e `operationId`)."""
    return {}


def _identifiers(text: str) -> tuple[str, str]:
    resource = re.search(r"resourceId\s+(\S+)", text)
    operation = re.search(r"operationId\s+(\S+)", text)
    assert resource and operation, text
    return resource.group(1), operation.group(1)


def _converged(sk: Sk, link: dict[str, str], *, on: bool) -> str:
    """Espera a ligação em `Ready` com a Operation `completed`; devolve a saída do `get`."""
    expected = "ligado" if on else "desligado"

    def check() -> str | None:
        done = sk.run(
            *("sum", "service", "get"),
            *("--resource-id", link["resourceId"]),
            *("--operation-id", link["operationId"]),
        )
        ready = done.exit_code == 0 and "Ready" in done.stdout and "completed" in done.stdout
        return (
            done.stdout if ready and "Situação" in done.stdout and expected in done.stdout else None
        )

    return wait_until(check, f"a ligação {expected} em Ready e a Operation completed")


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


def test_a_new_account_already_holds_the_base_roles_of_the_sum(person: Person) -> None:
    """Sem roles `sum.ipm.get`, o Receiver do SUM responderia 403 à listagem."""
    done = person.sk.run("sum", "service", "list")
    assert done.exit_code == 0, done.text
    assert "Nenhuma ligação" in done.stdout


def test_enable_the_ipm_and_see_its_roles_granted(person: Person, link: dict[str, str]) -> None:
    done = person.sk.run("sum", "service", "enable", "--service", "ipm")
    assert done.exit_code == 0, done.text
    link["resourceId"], link["operationId"] = _identifiers(done.stdout)
    shown = _converged(person.sk, link, on=True)
    assert IPM_ROLE in shown, shown  # roles observadas, concedidas pelo Executor do SUM


def test_the_link_is_listed_and_a_second_enable_points_to_it(
    person: Person, link: dict[str, str], links_cleanup: list[str]
) -> None:
    links_cleanup.append(link["resourceId"])
    listed = person.sk.run("sum", "service", "list")
    assert listed.exit_code == 0 and link["resourceId"] in listed.stdout, listed.text
    again = person.sk.run("sum", "service", "enable", "--service", "ipm")
    assert again.exit_code == 1
    assert "Já existe uma ligação deste serviço" in again.stderr, again.stderr


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


def test_disable_converges_and_revokes_the_roles(person: Person, link: dict[str, str]) -> None:
    done = person.sk.run("sum", "service", "disable", "--resource-id", link["resourceId"])
    assert done.exit_code == 0, done.text
    link["operationId"] = _identifiers(done.stdout)[1]
    shown = _converged(person.sk, link, on=False)
    assert "nenhuma" in shown, shown


def test_a_second_disable_has_nothing_to_do(person: Person, link: dict[str, str]) -> None:
    done = person.sk.run("sum", "service", "disable", "--resource-id", link["resourceId"])
    assert done.exit_code == 0, done.text
    assert "já está desligada" in done.stdout
