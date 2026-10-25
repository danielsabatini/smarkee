"""Jornada completa: login, ligar o `ipm`, a Organization e os usuários, renovar e desligar.

Os testes compartilham a mesma pessoa (fixture `person`) e a mesma ligação: cada um depende do
anterior, como os passos de uma pessoa usando a plataforma.
"""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta

import conftest
import psycopg
import pytest
from conftest import SUM_MANAGER_DATABASE_URL, Person, Sk, wait_until

IPM_PERMISSION_PREFIX = "ipm.organization"
USER_QUOTA = 5  # cota provisória de usuários por Organization (decisão 0077)


def _project(name: str) -> str:
    """ID do projeto de permissões da variável `E2E_<NOME>_PROJECT_ID` (a fixture já a exigiu)."""
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


def _plain(shown: str) -> str:
    """Texto de um painel da CLI sem as bordas, numa linha: a quebra da caixa não corta a frase."""
    return " ".join(re.sub(r"[│╭╮╰╯─]", " ", shown).split())


def _field(shown: str, name: str) -> str:
    match = re.search(rf"^[│\s]*{name}\s+(.+?)[│\s]*$", shown, re.MULTILINE)
    assert match, f"campo {name} ausente em:\n{shown}"
    return match.group(1)


def _email() -> str:
    return f"e2e-user-{uuid.uuid4().hex[:10]}@example.com"


def _create_user(
    sk: Sk,
    organization_id: str,
    users: list[str],
    *,
    email: str,
    permissions: tuple[str, ...] = (),
    roles: tuple[str, ...] = (),
) -> str:
    """Um usuário pela CLI até `Ready`: a Organization já tem o Grant (decisão 0081)."""
    created = sk.run(
        *("ipm", "user", "create"),
        *("--name", "Usuario", "--surname", f"E2e {len(users)}"),
        *("--email", email),
        *("--organization-id", organization_id),
        *(item for permission in permissions for item in ("--permission", permission)),
        *(item for role in roles for item in ("--role", role)),
        "--wait",
        timeout=150.0,
    )
    assert created.exit_code == 0, created.text
    users.append(_identifiers(created.stdout)[0])
    assert _field(created.stdout, "phase") == "Ready", created.stdout
    return created.stdout


def _delete_users(sk: Sk, users: list[str]) -> None:
    """Tenta remover todos antes de falhar: um usuário que não sai não deixa os outros para trás."""
    failures: list[str] = []
    for user in users:
        deleted = sk.run(
            *("ipm", "user", "delete"), *("--resource-id", user), "--wait", timeout=150.0
        )
        if deleted.exit_code != 0:
            failures.append(deleted.text)
    assert not failures, failures


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
    # Decisão 0033: uma revogação de permissão chega ao token em até 15 minutos.
    assert person.sk.token_lifetime_seconds() <= 900, person.sk.token_lifetime_seconds()


def test_a_new_account_already_holds_the_base_permissions_of_the_sum(person: Person) -> None:
    """Sem permissões `sum.ipm.get`, o Receiver do SUM responderia 403 à listagem."""
    done = person.sk.run("sum", "service", "list")
    assert done.exit_code == 0, done.text
    assert "No services" in done.stdout


def test_enable_wait_converges_and_the_token_already_carries_the_ipm_permissions(
    person: Person, link: dict[str, str]
) -> None:
    assert _project("IPM") not in person.sk.token_permissions(), (
        "antes de ligar, o token não tem ipm.*"
    )
    done = person.sk.run("sum", "service", "enable", "--service", "ipm", "--wait", timeout=150.0)
    assert done.exit_code == 0, done.text
    link["resourceId"], link["operationId"] = _identifiers(done.stdout)
    assert _field(done.stdout, "state") == "enabled" and _field(done.stdout, "phase") == "Ready"
    assert _field(done.stdout, "session") == "renewed", done.stdout
    shown = _state(person.sk, link)
    assert _field(shown, "operationStatus") == "completed"
    assert IPM_PERMISSION_PREFIX in _field(
        shown, "observedPermissions"
    )  # permissões observadas no Zitadel
    # O que a opção A garante: o token da sessão já reflete a ligação, sem novo login.
    permissions = person.sk.token_permissions()
    assert permissions.get(_project("IPM"), set()) >= {
        f"{IPM_PERMISSION_PREFIX}.get",
        f"{IPM_PERMISSION_PREFIX}.create",
    }, permissions
    assert {"core.account.get", "core.account.delete"} <= permissions[_project("CORE")]
    assert {"sum.ipm.enable", "sum.ipm.get"} <= permissions[_project("SUM")]
    assert {"bsm.account.get", "bsm.account.delete"} <= permissions[_project("BSM")]


def test_the_link_is_listed_and_a_second_enable_points_to_it(
    person: Person, link: dict[str, str], links_cleanup: list[str]
) -> None:
    links_cleanup.append(link["resourceId"])
    listed = person.sk.run("sum", "service", "list")
    assert listed.exit_code == 0 and link["resourceId"] in listed.stdout, listed.text
    again = person.sk.run("sum", "service", "enable", "--service", "ipm")
    assert again.exit_code == 1
    assert "This service is already enabled" in again.stderr, again.stderr


def test_the_organization_and_its_users_are_managed_with_the_sk(
    person: Person, link: dict[str, str]
) -> None:
    """Com o `ipm` ligado, o token traz `ipm.*`: a Organization e os usuários pela CLI."""
    sk = person.sk
    name = f"e2e-{uuid.uuid4().hex[:10]}"
    renamed = name + "-b"
    users: list[str] = []
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

        # Nome fora do contrato: recusado pela CLI antes da rede.
        bad_name = sk.run("ipm", "organization", "create", "--name", "Acme Inc")
        assert bad_name.exit_code == 2, bad_name.text
        assert "Fix --name" in _plain(bad_name.stderr), bad_name.stderr

        # A cota do dono é de uma Organization: o segundo pedido é recusado com a orientação.
        second = sk.run("ipm", "organization", "create", "--name", name + "-2")
        assert second.exit_code == 1, second.text
        assert "Organization limit" in " ".join(second.stderr.split()), second.stderr

        # Usuários da Organization (decisões 0077 e 0083): o primeiro criado com role específica
        # (`ipm.userViewer`), expandida pelo Manager em permissões atômicas.
        first_email = _email()
        first = _create_user(
            sk,
            created_id,
            users,
            email=first_email,
            roles=("ipm.userViewer",),
        )
        assert _field(first, "roles") == "ipm.userViewer", first
        assert _field(first, "permissions") == "ipm.user.get, ipm.user.list", first

        # Atualização de role para verificar efetividade e evolução de permissões:
        # Troca de ipm.userViewer para ipm.userAdmin:
        updated_role = sk.run(
            *("ipm", "user", "update"),
            *("--resource-id", users[0]),
            *("--role", "ipm.userAdmin"),
            "--wait",
            timeout=150.0,
        )
        assert updated_role.exit_code == 0, updated_role.text
        shown_first = sk.run("ipm", "user", "get", "--resource-id", users[0])
        assert shown_first.exit_code == 0, shown_first.text
        assert _field(shown_first.stdout, "roles") == "ipm.userAdmin", shown_first.stdout
        plain_permissions = _plain(shown_first.stdout)
        for perm in (
            "ipm.user.bind",
            "ipm.user.create",
            "ipm.user.delete",
            "ipm.user.get",
            "ipm.user.list",
            "ipm.user.update",
        ):
            assert perm in plain_permissions, shown_first.stdout

        # Caminhos tristes dos usuários e das roles, antes de chegar à cota.
        outside_role = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "RoleFora"),
            *("--email", _email(), "--organization-id", created_id),
            *("--role", "bsm.accountAdmin"),
        )
        assert outside_role.exit_code == 2, outside_role.text
        assert "not allowed for the Organization" in _plain(outside_role.stderr), (
            outside_role.stderr
        )

        malformed_role = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "RoleInvalida"),
            *("--email", _email(), "--organization-id", created_id),
            *("--role", "role-sem-ponto"),
        )
        assert malformed_role.exit_code == 2, malformed_role.text
        assert "role invalid" in _plain(malformed_role.stderr), malformed_role.stderr

        outside = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "Fora"),
            *("--email", _email(), "--organization-id", created_id),
            *("--permission", "ipm.organization.delete"),  # formato válido, fora do catálogo
        )
        assert outside.exit_code == 2, outside.text  # o `400` da API sai como erro de uso
        assert "not allowed for the Organization" in _plain(outside.stderr), outside.stderr
        malformed = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "Formato"),
            *("--email", _email(), "--organization-id", created_id, "--permission", "admin"),
        )
        assert malformed.exit_code == 2, malformed.text  # recusado antes da rede
        assert "permission invalid" in _plain(malformed.stderr), malformed.stderr
        repeated = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "Repetido"),
            *("--email", first_email, "--organization-id", created_id),
            "--wait",
            timeout=150.0,
        )
        assert repeated.exit_code == 1, repeated.text  # e-mail único na Organization
        assert "already in use in the Organization" in _plain(repeated.stderr), repeated.stderr
        elsewhere = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "Alheia"),
            *("--email", _email(), "--organization-id", str(uuid.uuid7())),
        )
        assert elsewhere.exit_code == 1, elsewhere.text  # Organization que não é dele

        # Proteção do usuário (nasce desprotegido, decisão 0077): protegido, não sai.
        protected = sk.run(
            *("ipm", "user", "protect", "--resource-id", users[0]), "--wait", timeout=150.0
        )
        assert protected.exit_code == 0, protected.text
        kept = sk.run("ipm", "user", "delete", "--resource-id", users[0])
        assert kept.exit_code == 1, kept.text
        assert "sk ipm user unprotect" in _plain(kept.stderr), kept.stderr
        opened_user = sk.run(
            *("ipm", "user", "unprotect", "--resource-id", users[0]), "--wait", timeout=150.0
        )
        assert opened_user.exit_code == 0, opened_user.text

        # Até a cota, e o seguinte é recusado.
        while len(users) < USER_QUOTA:
            _create_user(sk, created_id, users, email=_email())
        listed_users = sk.run("ipm", "user", "list", "--organization-id", created_id)
        assert listed_users.exit_code == 0, listed_users.text
        assert all(user in listed_users.stdout for user in users), listed_users.stdout
        over = sk.run(
            *("ipm", "user", "create"),
            *("--name", "Usuario", "--surname", "Excedente"),
            *("--email", f"e2e-user-{uuid.uuid4().hex[:10]}@example.com"),
            *("--organization-id", created_id),
        )
        assert over.exit_code == 1, over.text
        assert "user limit" in " ".join(over.stderr.split()), over.stderr

        # Proteção contra exclusão (decisão 0043): a conta e a Organization nascem protegidas.
        shown_account = sk.run("account", "get")
        assert _field(shown_account.stdout, "protected") == "yes", shown_account.text
        assert _field(shown.stdout, "protected") == "yes", shown.text
        protected_account = sk.run("account", "delete", "--yes")
        assert protected_account.exit_code == 1, protected_account.text
        assert "sk account unprotect" in " ".join(protected_account.stderr.split())
        protected_org = sk.run("ipm", "organization", "delete", "--resource-id", created_id)
        assert protected_org.exit_code == 1, protected_org.text
        assert "sk ipm organization unprotect" in " ".join(protected_org.stderr.split())
        opened = sk.run("account", "unprotect", "--wait", timeout=150.0)
        assert opened.exit_code == 0, opened.text
        assert _field(sk.run("account", "get").stdout, "protected") == "no"

        # Exclusão segura (decisão 0040): com uma Organization e o `ipm` habilitado, a conta fica.
        refused = sk.run("account", "delete", "--yes")
        assert refused.exit_code == 1, refused.text
        text = _plain(refused.stderr)
        assert "still has Organizations" in text and "sk ipm organization delete" in text, text

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

        # Só vazia (decisão 0077): desprotegida, a Organization com usuários ainda não sai.
        unprotected = sk.run(
            *("ipm", "organization", "unprotect"),
            *("--resource-id", created_id),
            "--wait",
            timeout=150.0,
        )
        assert unprotected.exit_code == 0, unprotected.text
        with_users = sk.run("ipm", "organization", "delete", "--resource-id", created_id)
        assert with_users.exit_code == 1, with_users.text
        assert "sk ipm user delete" in " ".join(with_users.stderr.split()), with_users.stderr
    finally:
        if created_id is not None:
            _delete_users(sk, users)
            assert (
                "No users" in sk.run("ipm", "user", "list", "--organization-id", created_id).stdout
            )
            unprotected = sk.run(
                *("ipm", "organization", "unprotect"),
                *("--resource-id", created_id),
                "--wait",
                timeout=150.0,
            )
            assert unprotected.exit_code == 0, unprotected.text
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


def test_disable_wait_converges_and_the_token_drops_the_ipm_permissions(
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
    assert _field(_state(person.sk, link), "observedPermissions") == "none"
    # A revogação também chega ao token: sem isso, o Receiver do ipm ainda aceitaria as permissões.
    permissions = person.sk.token_permissions()
    assert _project("IPM") not in permissions, permissions


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
    """Sem recursos atrelados (Organization, `ipm` e Billing Account), a conta sai."""
    shown = person.sk.run("account", "get")
    assert shown.exit_code == 0, shown.text
    assert person.email in shown.stdout and person.resource_id in shown.stdout
    bsm_listed = person.sk.run("bsm", "account", "list")
    assert bsm_listed.exit_code == 0, bsm_listed.text
    for bsm_id in re.findall(
        r"^[│\s]*([0-9a-f]{8}-[0-9a-f-]{27})\b", bsm_listed.stdout, re.MULTILINE
    ):
        unprotected_bsm = person.sk.run(
            "bsm", "account", "unprotect", "--resource-id", bsm_id, "--wait", timeout=150.0
        )
        assert unprotected_bsm.exit_code == 0, unprotected_bsm.text
        deleted_bsm = person.sk.run(
            "bsm", "account", "delete", "--resource-id", bsm_id, "--wait", timeout=150.0
        )
        assert deleted_bsm.exit_code == 0, deleted_bsm.text
    if _field(shown.stdout, "protected") == "yes":
        refused = person.sk.run("account", "delete", "--yes")
        assert refused.exit_code == 1, refused.text
        assert "sk account unprotect" in _plain(refused.stderr), refused.stderr
        unprotected_acc = person.sk.run("account", "unprotect", "--wait", timeout=150.0)
        assert unprotected_acc.exit_code == 0, unprotected_acc.text
    deleted = person.sk.run("account", "delete", "--yes", "--wait", timeout=150.0)
    assert deleted.exit_code == 0, deleted.text
    assert "Account deleted" in deleted.stdout, deleted.text
    assert not person.sk.credentials_path.exists(), "a sessão local deve ser esquecida"
    # Decisão 0044: o SUM apaga as ligações do dono quando a conta é removida.
    if SUM_MANAGER_DATABASE_URL:
        with psycopg.connect(SUM_MANAGER_DATABASE_URL, autocommit=True) as manager:

            def no_links_left() -> bool | None:
                found = manager.execute(
                    "SELECT count(*) FROM sum.service WHERE owner_account_id = %s",
                    (person.resource_id,),
                ).fetchone()
                return True if found is not None and found[0] == 0 else None

            wait_until(no_links_left, "a remoção das ligações do SUM da conta apagada")
