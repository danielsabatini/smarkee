"""Entrypoint do CLI `sk` da plataforma smarkee."""

from importlib.metadata import version as package_version
from typing import Annotated

import typer

from sk import output, ui
from sk.command_app import SkTyper
from sk.commands.account import account_app
from sk.commands.auth import auth_app
from sk.commands.bsm import bsm_app
from sk.commands.config import config_app
from sk.commands.ipm import ipm_app
from sk.commands.sum import sum_app
from sk.help import option

DOCUMENTATION_URL = "https://docs.smarkee.com.br"

app = SkTyper(
    name="sk",
    help="Smarkee Platform Command Line Interface (CLI).",
    epilog=f"Documentation: {DOCUMENTATION_URL}",
    # `-h` vale como `--help` em toda a árvore: o contexto de cada subcomando herda da raiz.
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    # Explícito: mostrar variáveis locais em erros exporia tokens.
    pretty_exceptions_show_locals=False,
)


def _show_version(requested: bool) -> None:
    """Callback ansioso de `--version`: imprime a versão do pacote e encerra o comando."""
    if requested:
        typer.echo(f"sk {package_version('sk')}")
        raise typer.Exit()


@app.callback()
def root(
    output_format: Annotated[
        output.OutputFormat,
        typer.Option(
            "--output",
            case_sensitive=False,
            help=option(
                "Result format: table (boxes and tables) or json (one JSON document on the "
                "standard output, for scripts). Goes before the command, as in "
                "`sk --output json ipm role list`.",
                kind="String",
                variable=None,
                file=None,
                default="table",
            ),
        ),
    ] = output.OutputFormat.TABLE,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help=option(
                "Plain output for scripts: no boxes, colors or decoration; tables become "
                "tab-separated lines with a header, and json becomes a single line. Goes "
                "before the command, as in `sk --raw ipm role list`.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help=option(
                "Show the sk version and exit.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
) -> None:
    # Grava o modo a cada execução, inclusive o padrão, para um estado não vazar para a seguinte.
    output.configure(raw=raw, output_format=output_format)


app.add_typer(auth_app, name="auth")
app.add_typer(config_app, name="config")
app.add_typer(ipm_app, name="ipm")
app.add_typer(bsm_app, name="bsm")
app.add_typer(sum_app, name="sum")
app.add_typer(account_app, name="account")


EXIT_FAILURE = 1


def main() -> None:
    """Executa o `sk`. Uma exceção que nenhum comando tratou vira um painel de erro (código 1).

    A captura fica aqui, e não nos comandos, para os testes com `CliRunner` continuarem vendo a
    exceção original. Só o **tipo** é mostrado: a mensagem pode trazer token ou resposta da API.
    `KeyboardInterrupt`, `SystemExit` e `typer.Exit` não são `Exception` e seguem seu curso.
    """
    try:
        app()
    except Exception as error:
        ui.error(
            "Unexpected error",
            f"The command failed with {type(error).__name__}.",
            hint=f"This is a bug in sk. Documentation: {DOCUMENTATION_URL}",
        )
        raise SystemExit(EXIT_FAILURE) from None
