"""Opção global `--raw` (decisão 0093): saída sem caixa nem cor, TSV nas tabelas e limpeza de
escapes. A limpeza vale também no modo padrão."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from typer.testing import CliRunner

from sk import output, ui
from sk.identity.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.main import app

runner = CliRunner()
API = "https://api.teste"
RID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
ESCAPE = "\x1b"


@pytest.fixture(autouse=True)
def default_mode() -> Iterator[None]:
    output.configure(raw=False)
    yield
    output.configure(raw=False)


def test_sanitize_removes_escape_sequences_and_controls_but_keeps_tab_and_newline() -> None:
    dirty = f"a{ESCAPE}[31mred{ESCAPE}[0m{ESCAPE}]0;title\x07b\x00c\x7fd\x9be\tf\ng"
    assert output.sanitize(dirty) == "aredbcde\tf\ng"


def test_sanitize_removes_an_osc_terminated_by_string_terminator() -> None:
    assert output.sanitize(f"x{ESCAPE}]8;;http://evil{ESCAPE}\\y") == "xy"


def test_flatten_turns_tabs_and_line_breaks_into_a_single_space() -> None:
    assert output.flatten("a\tb\nc\n\nd ") == "a b c d"


def test_flatten_drops_carriage_return_because_it_could_overwrite_the_line() -> None:
    assert output.flatten("safe\rEVIL") == "safeEVIL"


def test_raw_panel_prints_label_tab_value_lines(capsys: pytest.CaptureFixture[str]) -> None:
    output.configure(raw=True)
    ui.panel("Role", [("resourceId", RID), ("name", "ipm.userAdmin")])
    assert capsys.readouterr().out == f"resourceId\t{RID}\nname\tipm.userAdmin\n"


def test_raw_table_prints_a_header_and_one_line_per_record(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output.configure(raw=True)
    ui.table("Roles", ["name", "state"], [["a", Text("Ready", style="green")], ["b", "Failed"]])
    assert capsys.readouterr().out == "name\tstate\na\tReady\nb\tFailed\n"


def test_raw_table_keeps_columns_aligned_when_a_value_has_tab_or_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output.configure(raw=True)
    ui.table("Roles", ["name", "description"], [["a", "one\ttwo\nthree"]])
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["name\tdescription", "a\tone two three"]
    assert {len(line.split("\t")) for line in lines} == {2}


def test_raw_does_not_interpret_square_brackets(capsys: pytest.CaptureFixture[str]) -> None:
    output.configure(raw=True)
    ui.panel("Role", [("description", "[bold]not markup[/bold]")])
    assert capsys.readouterr().out == "description\t[bold]not markup[/bold]\n"


def test_raw_note_goes_to_stderr_and_keeps_stdout_for_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output.configure(raw=True)
    ui.panel("Role", [("name", "x")])
    ui.note("Follow it with `sk ipm role get`.")
    captured = capsys.readouterr()
    assert captured.out == "name\tx\n"
    assert "Follow it with" in captured.err


def test_default_note_stays_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    ui.note("Follow it with `sk ipm role get`.")
    captured = capsys.readouterr()
    assert "Follow it with" in captured.out and captured.err == ""


def test_default_panel_and_table_drop_escape_sequences_from_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ui.panel("Role", [("name", f"evil{ESCAPE}[31mRED{ESCAPE}]0;pwned\x07")])
    ui.table("Roles", ["name"], [[f"evil{ESCAPE}[31mRED"], [Text(f"ok{ESCAPE}[2J", style="green")]])
    printed = capsys.readouterr().out
    assert ESCAPE not in printed and "\x07" not in printed
    assert "evilRED" in printed and "ok" in printed


def test_error_and_warning_drop_escape_sequences(capsys: pytest.CaptureFixture[str]) -> None:
    ui.error("Failed", f"server said{ESCAPE}[31m boom", hint=f"try{ESCAPE}]0;x\x07 again")
    ui.warning(f"careful{ESCAPE}[2J")
    printed = capsys.readouterr().err
    assert ESCAPE not in printed and "\x07" not in printed
    assert "boom" in printed and "again" in printed and "careful" in printed


# --- pela CLI, com a API simulada -------------------------------------------------------------


class Response:
    def __init__(self, document: object) -> None:
        self.status = 200
        self._body = json.dumps(document).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def role_document(description: str) -> dict[str, Any]:
    return {
        "resourceId": RID,
        "resourceVersion": "1",
        "desiredGeneration": 1,
        "phase": "Ready",
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "organizationId": "org-acme",
            "specification": {
                "name": "ipm.userAdmin",
                "description": description,
                "permissions": ["ipm.user.get", "ipm.user.list"],
                "deletionProtection": False,
                "status": "active",
            },
        },
        "createdAt": "2026-10-25T10:00:00+00:00",
        "updatedAt": "2026-10-25T10:00:05+00:00",
    }


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Response]]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(f'[api]\nurl = "{API}"\n', encoding="utf-8")
    routes: dict[str, Response] = {}

    def fake(request: urllib.request.Request, timeout: float = 0) -> Response:
        return routes[request.full_url.removeprefix(API).split("?")[0]]

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    save_credentials(
        default_credentials_path(),
        StoredCredentials(
            issuer="https://ipm.teste",
            client_id="cli",
            token_type="Bearer",
            access_token="access-1",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token="refresh-1",
            id_token=None,
            scope="openid",
            obtained_at=datetime.now(UTC),
        ),
    )
    yield routes


def test_raw_get_prints_label_value_lines_without_a_box(served: dict[str, Response]) -> None:
    served[f"/v1/ipm/roles/{RID}"] = Response(role_document("Administrador de usuários"))
    result = runner.invoke(app, ["--raw", "ipm", "role", "get", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert f"resourceId\t{RID}" in lines
    assert "name\tipm.userAdmin" in lines
    assert "permissions\tipm.user.get, ipm.user.list" in lines
    assert not any(symbol in result.stdout for symbol in "╭╰│✓")


def test_raw_list_prints_a_tsv_with_header(served: dict[str, Response]) -> None:
    served["/v1/ipm/roles"] = Response({"items": [role_document("Admin\tcom\ntab")]})
    result = runner.invoke(app, ["--raw", "ipm", "role", "list"])
    assert result.exit_code == 0, result.stderr
    header, record = result.stdout.splitlines()
    assert header.split("\t") == ["name", "resourceId", "phase", "description"]
    assert record.split("\t") == ["ipm.userAdmin", RID, "Ready", "Admin com tab"]


def test_without_raw_the_output_keeps_the_panel(served: dict[str, Response]) -> None:
    served[f"/v1/ipm/roles/{RID}"] = Response(role_document("Administrador de usuários"))
    result = runner.invoke(app, ["ipm", "role", "get", "--resource-id", RID])
    assert result.exit_code == 0 and "╭" in result.stdout and "✓ Role" in result.stdout


def test_raw_applies_only_to_its_own_invocation(served: dict[str, Response]) -> None:
    served[f"/v1/ipm/roles/{RID}"] = Response(role_document("Administrador de usuários"))
    runner.invoke(app, ["--raw", "ipm", "role", "get", "--resource-id", RID])
    again = runner.invoke(app, ["ipm", "role", "get", "--resource-id", RID])
    assert "╭" in again.stdout  # o modo não vazou da execução anterior


def test_raw_after_the_subcommand_is_refused(served: dict[str, Response]) -> None:
    result = runner.invoke(app, ["ipm", "role", "list", "--raw"])
    assert result.exit_code == 2
