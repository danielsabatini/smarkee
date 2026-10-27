"""`-q`/`--quiet` (decisão 0095): some o que é informativo; erro, aviso e dado permanecem."""

from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from sk import output, ui
from sk.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def default_mode() -> Iterator[None]:
    output.configure(raw=False)
    yield
    output.configure(raw=False)


def test_without_quiet_the_note_is_shown() -> None:
    result = runner.invoke(app, ["config", "unset", "api.url"])
    assert "already at the default" in result.output


def test_quiet_hides_the_guidance_note() -> None:
    result = runner.invoke(app, ["-q", "config", "unset", "api.url"])
    assert result.exit_code == 0
    assert "already at the default" not in result.output


def test_the_long_name_works_the_same() -> None:
    result = runner.invoke(app, ["--quiet", "config", "unset", "api.url"])
    assert result.exit_code == 0
    assert "already at the default" not in result.output


def test_quiet_keeps_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SK_API_URL", "https://from-env.example")
    result = runner.invoke(app, ["-q", "config", "unset", "api.url"])
    assert result.exit_code == 0
    assert "SK_API_URL is set" in result.output
    assert "already at the default" not in result.output


def test_quiet_keeps_errors() -> None:
    result = runner.invoke(app, ["-q", "config", "unset", "api.nada"])
    assert result.exit_code == 2
    assert "api.nada" in result.output


def test_quiet_keeps_the_result_panel() -> None:
    result = runner.invoke(app, ["-q", "config", "set", "api.timeoutSeconds", "30"])
    assert result.exit_code == 0
    assert "Configuration updated" in result.output
    assert "api.timeoutSeconds" in result.output


def test_quiet_keeps_the_json_document() -> None:
    result = runner.invoke(app, ["-q", "--output", "json", "config", "list"])
    assert result.exit_code == 0
    assert result.stdout.lstrip().startswith(("{", "["))


def test_quiet_hides_an_empty_list_note() -> None:
    ui.empty("Nothing here.")  # sem --quiet
    output.configure(raw=False, quiet=True)
    ui.empty("Nothing here.")


def test_quiet_after_the_command_is_refused() -> None:
    result = runner.invoke(app, ["config", "unset", "api.url", "--quiet"])
    assert result.exit_code == 2


def test_quiet_silences_the_wait_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    output.configure(raw=False, quiet=True)
    with ui.waiting(60) as progress:
        progress.update("phase Pending")
    assert err.getvalue() == ""


def test_the_mode_does_not_leak_to_the_next_run() -> None:
    runner.invoke(app, ["-q", "config", "unset", "api.url"])
    result = runner.invoke(app, ["config", "unset", "api.url"])
    assert "already at the default" in result.output
