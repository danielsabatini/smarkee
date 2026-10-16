"""Padrão dos textos de ajuda: todo comando explica a ordem de resolução, e toda opção segue o
formato `<descrição> [Tipo] [env … | arquivo … | padrão …] [obrigatório|opcional]`, com o bloco de
fontes omitido quando não há nenhuma. Flags são `Booleano`, números são `Inteiro` e as demais,
`String`."""

import re
from typing import Any

import typer.main
from rich.text import Text
from typer.core import TyperOption
from typer.testing import CliRunner

from sk.main import app

runner = CliRunner()
# `--timeout` usa um intervalo inteiro (`min=1`), cujo tipo se chama "int range".
INTEGER_TYPES = {"integer", "int range"}
IGNORED = {"help", "install_completion", "show_completion"}
# Os subcomandos de `sk config` operam só no arquivo: não há ordem de resolução a explicar.
WITHOUT_RESOLUTION_ORDER = {"config list", "config get", "config set"}
OPTION_FORMAT = re.compile(r"\[(String|Integer|Boolean)\](?: \[(.+)\])? \[(required|optional)\]$")


def _commands() -> list[tuple[str, Any]]:
    """Todos os comandos (em qualquer nível) e os grupos que têm opções próprias."""
    found: list[tuple[str, Any]] = []

    def walk(prefix: str, group: Any) -> None:
        for name, command in group.commands.items():
            path = f"{prefix} {name}".strip()
            if getattr(command, "commands", None):
                if _options(command):  # grupo com opções próprias (por exemplo, `register`)
                    found.append((path, command))
                walk(path, command)
            else:
                found.append((path, command))

    walk("", typer.main.get_command(app))
    return found


def _options(command: Any) -> list[Any]:
    # Argumentos posicionais (por exemplo, a chave de `sk config get`) não são opções.
    return [
        param
        for param in command.params
        if isinstance(param, TyperOption) and param.name not in IGNORED
    ]


def _help_text(param: Any) -> str:
    # O help tem markup do Rich (cores e "\\["); a comparação usa o texto exibido.
    return Text.from_markup(param.help or "").plain


def test_every_command_explains_the_resolution_order() -> None:
    for name, command in _commands():
        if name in WITHOUT_RESOLUTION_ORDER:
            continue
        assert "Resolution order" in (command.help or ""), name


def test_every_option_follows_the_type_and_resolution_format() -> None:
    for name, command in _commands():
        for param in _options(command):
            assert OPTION_FORMAT.search(_help_text(param)), f"{name} {param.name}"


def test_sources_are_labeled_and_in_resolution_order() -> None:
    order = ["env ", "file ", "default "]
    for name, command in _commands():
        for param in _options(command):
            match = OPTION_FORMAT.search(_help_text(param))
            assert match is not None, f"{name} {param.name}"
            if match.group(2) is None:
                continue
            parts = [part.strip() for part in match.group(2).split(" | ")]
            labels = [next(r for r in order if part.startswith(r)) for part in parts]
            assert labels == sorted(labels, key=order.index), f"{name} {param.name}: {parts}"


def test_options_without_other_sources_have_no_sources_block() -> None:
    for name, command in _commands():
        for param in _options(command):
            if name == "register" and param.name in {"name", "surname", "email"}:
                match = OPTION_FORMAT.search(_help_text(param))
                assert match is not None, f"{name} {param.name}"
                assert match.group(2) is None, f"{name} {param.name}"


def test_boolean_options_are_declared_as_boolean() -> None:
    for name, command in _commands():
        for param in _options(command):
            match = OPTION_FORMAT.search(_help_text(param))
            assert match is not None, f"{name} {param.name}"
            if getattr(param, "is_flag", False):
                expected_kind = "Boolean"
            elif getattr(param.type, "name", "") in INTEGER_TYPES:
                expected_kind = "Integer"
            else:
                expected_kind = "String"
            assert match.group(1) == expected_kind, f"{name} {param.name}"


def test_required_options_are_marked_as_required() -> None:
    required = {"name", "surname", "email"}  # os únicos valores sem padrão da plataforma
    with_default = {"issuer", "client_id", "api_url"}
    for name, command in _commands():
        for param in _options(command):
            match = OPTION_FORMAT.search(_help_text(param))
            assert match is not None, f"{name} {param.name}"
            status = match.group(3)
            if param.name in required:
                assert status == "required", f"{name} {param.name}"
            if param.name in with_default:
                assert status == "optional", f"{name} {param.name}"
                assert "default " in (match.group(2) or ""), f"{name} {param.name}"


def test_options_with_environment_variables_say_which_one() -> None:
    expected = {
        "issuer": "SK_AUTH_ISSUER",
        "client_id": "SK_AUTH_CLIENT_ID",
        "api_url": "SK_API_URL",
    }
    for name, command in _commands():
        for param in _options(command):
            if param.name in expected:
                assert expected[param.name] in _help_text(param), name


def test_bracketed_names_are_shown_literally() -> None:
    # Os colchetes do formato e dos valores aparecem como texto, e não viram tags do Rich.
    result = runner.invoke(app, ["register", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    assert "[String]" in result.stdout and "[required]" in result.stdout
    wait = runner.invoke(app, ["ipm", "organization", "create", "--help"], env={"COLUMNS": "200"})
    assert "[Integer]" in wait.stdout and "[default 60]" in wait.stdout


def test_register_required_options_are_checked_by_the_command() -> None:
    # Sem o "required" do Typer, a ausência é recusada pelo comando, com código 2.
    result = runner.invoke(app, ["register", "--surname", "B", "--email", "a@b.com"])
    assert result.exit_code == 2
    assert "--name" in result.output
    assert "Missing required option" in result.output


def test_required_options_show_a_single_required_marker() -> None:
    result = runner.invoke(app, ["register", "--help"])
    assert result.exit_code == 0
    # O nosso marcador tem o mesmo texto do do Typer: cada opção obrigatória mostra um só.
    options = ["--name", "--surname", "--email"]
    assert result.stdout.count("[required]") == len(options)
