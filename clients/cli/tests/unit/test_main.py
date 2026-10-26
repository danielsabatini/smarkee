"""`sk.main.main`: erro inesperado vira painel com código 1, sem traceback nem texto sensível."""

import pytest

from sk import main as main_module


def test_unexpected_error_shows_a_panel_with_only_the_exception_type(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Bearer segredo-do-token")

    monkeypatch.setattr(main_module, "app", explode)
    with pytest.raises(SystemExit) as raised:
        main_module.main()
    captured = capsys.readouterr()
    assert raised.value.code == 1
    assert "Unexpected error" in captured.err
    assert "RuntimeError" in captured.err
    assert main_module.DOCUMENTATION_URL in captured.err
    assert "segredo-do-token" not in captured.err + captured.out
    assert "Traceback" not in captured.err


def test_exit_codes_of_handled_outcomes_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["sk", "--version"])
    with pytest.raises(SystemExit) as finished:
        main_module.main()
    assert finished.value.code == 0
    monkeypatch.setattr("sys.argv", ["sk", "--opcao-inexistente"])
    with pytest.raises(SystemExit) as raised:
        main_module.main()
    assert raised.value.code == 2


def test_keyboard_interrupt_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "app", interrupt)
    with pytest.raises(KeyboardInterrupt):
        main_module.main()
