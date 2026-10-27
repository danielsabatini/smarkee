"""Progresso de espera (`sk.ui.waiting`): só na saída de erro, sem resíduo no terminal."""

import io

import pytest

from sk import ui


class Stream(io.StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _streams(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> tuple[Stream, Stream]:
    out, err = Stream(tty=tty), Stream(tty=tty)
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    monkeypatch.setenv("TERM", "xterm")
    return out, err


def test_outside_a_terminal_one_line_per_state_change(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _streams(monkeypatch, tty=False)
    with ui.waiting(60) as progress:
        for state in ("phase Pending", "phase Pending", "phase Pending", "phase Ready"):
            progress.update(state)
    lines = err.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("waiting: phase Pending (")
    assert "of 60 s" in lines[0]
    assert lines[1].startswith("waiting: phase Ready (")
    assert "\x1b" not in err.getvalue()
    assert out.getvalue() == ""


def test_in_a_terminal_the_indicator_is_erased_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _streams(monkeypatch, tty=True)
    with ui.waiting(60) as progress:
        progress.update("phase Pending")
        progress.update("phase Pending")
    written = err.getvalue()
    assert "phase Pending" in written
    assert "\n" not in written  # tudo numa só linha
    assert written.endswith("\r\x1b[2K")  # a última escrita apaga o indicador
    assert out.getvalue() == ""


def test_in_a_terminal_the_indicator_is_erased_even_when_the_wait_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, err = _streams(monkeypatch, tty=True)
    with pytest.raises(KeyboardInterrupt), ui.waiting(60) as progress:
        progress.update("phase Pending")
        raise KeyboardInterrupt
    assert err.getvalue().endswith("\r\x1b[2K")


def test_a_message_printed_during_the_wait_does_not_start_on_the_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, err = _streams(monkeypatch, tty=True)
    with ui.waiting(60) as progress:
        progress.update("phase Pending")
        ui.error("Request not completed", "The Operation ended as failed.")
    written = err.getvalue()
    assert written.index("\r\x1b[2K", written.index("phase Pending")) < written.index("Request")


def test_a_dumb_terminal_gets_lines_instead_of_the_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, err = _streams(monkeypatch, tty=True)
    monkeypatch.setenv("TERM", "dumb")
    with ui.waiting(60) as progress:
        progress.update("phase Pending")
    assert err.getvalue().startswith("waiting: phase Pending")


def test_the_state_from_outside_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    _, err = _streams(monkeypatch, tty=False)
    with ui.waiting(60) as progress:
        progress.update("phase \x1b[31mEvil\x1b[0m")
    assert "\x1b" not in err.getvalue()
