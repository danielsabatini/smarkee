"""Padrão dos textos de ajuda: todo comando explica a ordem de resolução, e toda opção segue o
formato `<descrição> [Tipo] [env … | arquivo … | padrão …] [obrigatório|opcional]`, com o bloco de
fontes omitido quando não há nenhuma. Flags são `Booleano`; as demais, `String`."""

import re
from typing import Any

import typer.main
from rich.text import Text
from typer.testing import CliRunner

from sk.main import app

runner = CliRunner()
IGNORED = {"help", "install_completion", "show_completion"}
FORMATO_OPCAO = re.compile(r"\[(String|Booleano)\](?: \[(.+)\])? \[(obrigatório|opcional)\]$")


def _commands() -> list[tuple[str, Any]]:
    root: Any = typer.main.get_command(app)
    found: list[tuple[str, Any]] = []
    for name, command in root.commands.items():
        if getattr(command, "commands", None):
            for sub_name, sub in command.commands.items():
                found.append((f"{name} {sub_name}", sub))
        else:
            found.append((name, command))
    return found


def _options(command: Any) -> list[Any]:
    return [param for param in command.params if param.name not in IGNORED]


def _texto(param: Any) -> str:
    # O help tem markup do Rich (cores e "\\["); a comparação usa o texto exibido.
    return Text.from_markup(param.help or "").plain


def test_every_command_explains_the_resolution_order() -> None:
    for name, command in _commands():
        assert "Ordem de resolução" in (command.help or ""), name


def test_every_option_follows_the_type_and_resolution_format() -> None:
    for name, command in _commands():
        for param in _options(command):
            assert FORMATO_OPCAO.search(_texto(param)), f"{name} {param.name}"


def test_sources_are_labeled_and_in_resolution_order() -> None:
    ordem = ["env ", "arquivo ", "padrão "]
    for name, command in _commands():
        for param in _options(command):
            match = FORMATO_OPCAO.search(_texto(param))
            assert match is not None, f"{name} {param.name}"
            if match.group(2) is None:
                continue
            partes = [parte.strip() for parte in match.group(2).split(" | ")]
            rotulos = [next(r for r in ordem if parte.startswith(r)) for parte in partes]
            assert rotulos == sorted(rotulos, key=ordem.index), f"{name} {param.name}: {partes}"


def test_options_without_other_sources_have_no_sources_block() -> None:
    for name, command in _commands():
        for param in _options(command):
            if name == "register" and param.name in {"name", "surname", "email"}:
                match = FORMATO_OPCAO.search(_texto(param))
                assert match is not None, f"{name} {param.name}"
                assert match.group(2) is None, f"{name} {param.name}"


def test_boolean_options_are_declared_as_boolean() -> None:
    for name, command in _commands():
        for param in _options(command):
            match = FORMATO_OPCAO.search(_texto(param))
            assert match is not None, f"{name} {param.name}"
            esperado = "Booleano" if getattr(param, "is_flag", False) else "String"
            assert match.group(1) == esperado, f"{name} {param.name}"


def test_required_options_are_marked_as_required() -> None:
    obrigatorias = {
        "issuer",
        "client_id",
        "api_url",
        "name",
        "surname",
        "email",
    }
    for name, command in _commands():
        for param in _options(command):
            match = FORMATO_OPCAO.search(_texto(param))
            assert match is not None, f"{name} {param.name}"
            situacao = match.group(3)
            if param.name in obrigatorias:
                assert situacao == "obrigatório", f"{name} {param.name}"


def test_options_with_environment_variables_say_which_one() -> None:
    expected = {
        "issuer": "SK_AUTH_ISSUER",
        "client_id": "SK_AUTH_CLIENT_ID",
        "api_url": "SK_CORE_API_URL",
    }
    for name, command in _commands():
        for param in _options(command):
            if param.name in expected:
                assert expected[param.name] in _texto(param), name


def test_bracketed_names_are_shown_literally() -> None:
    login = runner.invoke(app, ["auth", "login", "--help"], env={"COLUMNS": "200"})
    assert login.exit_code == 0
    assert "[auth] issuer" in login.stdout
    init = runner.invoke(app, ["auth", "init", "--help"], env={"COLUMNS": "200"})
    assert init.exit_code == 0
    assert "arquivo [auth]" not in init.stdout


def test_init_does_not_list_the_config_file_as_a_source() -> None:
    # O init não lê o arquivo que cria: a ajuda não pode dizer o contrário.
    for name, command in _commands():
        if name != "auth init":
            continue
        for param in _options(command):
            match = FORMATO_OPCAO.search(_texto(param))
            assert match is not None, param.name
            assert "[auth]" not in (match.group(2) or ""), param.name


def test_register_required_options_are_checked_by_the_command() -> None:
    # Sem o "required" do Typer, a ausência é recusada pelo comando, com código 2.
    result = runner.invoke(app, ["register", "--surname", "B", "--email", "a@b.com"])
    assert result.exit_code == 2
    assert "--name" in result.output
    assert "Opção obrigatória ausente" in result.output


def test_required_options_do_not_show_typers_required_tag() -> None:
    result = runner.invoke(app, ["register", "--help"])
    assert result.exit_code == 0
    assert "[required]" not in result.stdout
