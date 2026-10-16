"""Jornada: uma pessoa se cadastra, ativa a conta, entra pelo `sk` e liga o `ipm` pelo SUM.

Tudo pela rede e pela CLI real. O navegador é um falso (`login_browser.py`) que preenche as páginas
de login do provedor como a pessoa faria; nenhuma credencial privilegiada é usada.
"""

import base64
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from browser import Browser

API_URL = os.environ.get("E2E_API_URL", "http://api-dev.smarkee.com.br:8080")
ISSUER = os.environ.get("E2E_ISSUER", "http://ipm-dev.smarkee.com.br:8080")
MAILPIT_URL = os.environ.get("E2E_MAILPIT_URL", "http://localhost:8025")
CLI_CLIENT_ID = os.environ.get("E2E_CLI_CLIENT_ID")
CORE_PROJECT_ID = os.environ.get("E2E_CORE_PROJECT_ID")
SUM_PROJECT_ID = os.environ.get("E2E_SUM_PROJECT_ID")
IPM_PROJECT_ID = os.environ.get("E2E_IPM_PROJECT_ID")
CLI_PROJECT = Path(os.environ.get("E2E_CLI_PROJECT", Path(__file__).parents[3] / "clients" / "cli"))
SUM_MANAGER_DATABASE_URL = os.environ.get("E2E_SUM_MANAGER_DATABASE_URL")
SUM_MAINTENANCE_DATABASE_URL = os.environ.get("E2E_SUM_MAINTENANCE_DATABASE_URL")

LOGIN_BROWSER = Path(__file__).with_name("login_browser.py")
WAIT_SECONDS = 90.0
POLL_SECONDS = 1.5


@dataclass(frozen=True)
class Result:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        return self.stdout + self.stderr


class Sk:
    """A CLI real (`sk`), com a configuração e a sessão isoladas em uma pasta temporária."""

    def __init__(self, home: Path, login_name: str, password: str) -> None:
        self.home = home
        self.browser_log = home / "browser.log"
        self._env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("SK_", "XDG_"))},
            "XDG_CONFIG_HOME": str(home),
            "E2E_LOGIN_NAME": login_name,
            "E2E_LOGIN_PASSWORD": password,
            "E2E_BROWSER_LOG": str(self.browser_log),
            "BROWSER": f"{shlex.quote(sys.executable)} {shlex.quote(str(LOGIN_BROWSER))} %s",
        }
        (home / "sk").mkdir(parents=True)
        (home / "sk" / "config.toml").write_text(
            f'[auth]\nissuer = "{ISSUER}"\nclientId = "{CLI_CLIENT_ID}"\nallowInsecureHttp = true\n'
            f'[api]\nurl = "{API_URL}"\nallowInsecureHttp = true\n'
            f'[core]\nprojectId = "{CORE_PROJECT_ID}"\n'
            f'[sum]\nprojectId = "{SUM_PROJECT_ID}"\n'
            f'[ipm]\nprojectId = "{IPM_PROJECT_ID}"\n',
            encoding="utf-8",
        )

    def run(self, *arguments: str, timeout: float = 120.0) -> Result:
        done = subprocess.run(
            ["uv", "run", "--project", str(CLI_PROJECT), "sk", *arguments],
            env=self._env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return Result(done.returncode, done.stdout, done.stderr)

    @property
    def credentials_path(self) -> Path:
        return self.home / "sk" / "credentials.json"

    def credentials(self) -> dict[str, Any]:
        return json.loads(self.credentials_path.read_text(encoding="utf-8"))

    def token_lifetime_seconds(self) -> int:
        """Validade do access token da sessão atual (`exp` menos `iat`)."""
        token = str(self.credentials()["accessToken"])
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(claims["exp"]) - int(claims["iat"])

    def token_roles(self) -> dict[str, set[str]]:
        """Roles do access token da sessão atual, por ID de projeto (só as chaves, sem o token)."""
        token = str(self.credentials()["accessToken"])
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        prefix, suffix = "urn:zitadel:iam:org:project:", ":roles"
        return {
            key[len(prefix) : -len(suffix)]: set(value)
            for key, value in claims.items()
            if key.startswith(prefix) and key.endswith(suffix) and key.count(":") > 5
        }

    def browser_failure(self) -> str:
        return self.browser_log.read_text(encoding="utf-8") if self.browser_log.exists() else ""


@dataclass(frozen=True)
class Person:
    email: str
    resource_id: str
    sk: Sk


def wait_until[T](check: Callable[[], T | None], what: str, seconds: float = WAIT_SECONDS) -> T:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = check()
        if found is not None:
            return found
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"tempo esgotado esperando: {what}")


def _mail_links(email: str) -> dict[str, str]:
    """Links das mensagens enviadas ao endereço, por assunto."""

    def messages() -> dict[str, str] | None:
        found = httpx.get(
            f"{MAILPIT_URL}/api/v1/search", params={"query": f"to:{email}"}, timeout=10.0
        ).json()["messages"]
        links: dict[str, str] = {}
        for message in found:
            body = httpx.get(f"{MAILPIT_URL}/api/v1/message/{message['ID']}", timeout=10.0).json()
            match = re.search(r"\(\s*(http\S+)\s*\)", body["Text"])
            if match:
                links[message["Subject"]] = match.group(1)
        return links if "Verificar e-mail" in links else None

    return wait_until(messages, f"o e-mail de ativação de {email}")


def _query_value(url: str, name: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)[name][0]


def _require_environment() -> None:
    missing = [
        name
        for name, value in (
            ("E2E_CLI_CLIENT_ID", CLI_CLIENT_ID),
            ("E2E_CORE_PROJECT_ID", CORE_PROJECT_ID),
            ("E2E_SUM_PROJECT_ID", SUM_PROJECT_ID),
            ("E2E_IPM_PROJECT_ID", IPM_PROJECT_ID),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"variáveis não definidas: {', '.join(missing)}")
    try:
        httpx.get(MAILPIT_URL + "/api/v1/info", timeout=5.0).raise_for_status()
        httpx.get(API_URL, timeout=5.0)
    except httpx.HTTPError as error:
        pytest.skip(f"stack de dev indisponível: {type(error).__name__}")


@pytest.fixture(scope="module")
def person(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Person]:
    """Registra e ativa a conta (e-mail e senha pelos links), e remove a pessoa ao final."""
    _require_environment()
    email = f"e2e-{secrets.token_hex(4)}@example.com"
    password = "Aa1!" + secrets.token_urlsafe(14)
    registered = httpx.post(
        f"{API_URL}/v1/core/accounts",
        json={"givenName": "Jornada", "familyName": "E2e", "email": email},
        timeout=15.0,
    )
    assert registered.status_code == 202, registered.text
    resource_id = str(registered.json()["resourceId"])
    sk = Sk(tmp_path_factory.mktemp("sk"), email, password)
    created = Person(email, resource_id, sk)
    try:
        links = _mail_links(email)
        # Um e-mail só: o link de verificação confirma o e-mail e já define a senha.
        assert "Redefinir senha" not in links, "o cadastro não deve mandar o e-mail de redefinição"
        browser = Browser()
        try:
            verify = links["Verificar e-mail"]
            browser.submit_form(
                verify,
                {
                    "code": _query_value(verify, "code"),
                    "password": password,
                    "passwordconfirm": password,
                },
            )
        finally:
            browser.close()
        yield created
    finally:
        _remove(created)


def _remove(person: Person) -> None:
    """Remove a pessoa pela API, com o token dela. Falha alto: conta de teste não pode sobrar."""
    if not person.sk.credentials_path.exists():
        return  # o login nunca aconteceu: não há token, e a conta fica para a limpeza manual
    sk = person.sk
    sk.run("sum", "service", "list")  # renova o token se preciso (a CLI cuida da sessão)
    headers = {"Authorization": f"Bearer {sk.credentials()['accessToken']}"}
    url = f"{API_URL}/v1/core/accounts/{person.resource_id}"
    current = httpx.get(url, headers=headers, timeout=15.0)
    if current.status_code == 404:
        return
    assert current.status_code == 200, f"não foi possível ler a pessoa de teste: {current.text}"
    version = str(current.json()["resourceVersion"])
    if current.json()["desired"].get("deletionProtection", True):
        sk.run("account", "unprotect", "--wait", timeout=150.0)
        current = httpx.get(url, headers=headers, timeout=15.0)
        version = str(current.json()["resourceVersion"])
    deleted = httpx.delete(url, headers=headers, params={"resourceVersion": version}, timeout=15.0)
    assert deleted.status_code == 202, deleted.text
    wait_until(
        lambda: True if httpx.get(url, headers=headers, timeout=15.0).status_code == 404 else None,
        "a remoção da pessoa",
    )


@pytest.fixture(scope="module")
def links_cleanup(person: Person) -> Iterator[list[str]]:
    """Ligações do SUM criadas pela jornada; as linhas desligadas são limpas se houver acesso."""
    resource_ids: list[str] = []
    yield resource_ids
    if not resource_ids or not (SUM_MANAGER_DATABASE_URL and SUM_MAINTENANCE_DATABASE_URL):
        return
    import psycopg

    with (
        psycopg.connect(SUM_MANAGER_DATABASE_URL, autocommit=True) as manager,
        psycopg.connect(SUM_MAINTENANCE_DATABASE_URL, autocommit=True) as maintenance,
    ):
        present = manager.execute(
            "SELECT resource_id FROM sum.service "
            "WHERE resource_id = ANY(%s) AND lifecycle = 'present'",
            (resource_ids,),
        ).fetchall()
        assert not present, f"ligação ainda ligada no fim da jornada: {present}"
        for table in ("service_outbox", "service_operation", "service_action_result"):
            maintenance.execute(
                f"DELETE FROM sum.{table} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabela fixa)
                (resource_ids,),
            )
        manager.execute("DELETE FROM sum.service WHERE resource_id = ANY(%s)", (resource_ids,))
