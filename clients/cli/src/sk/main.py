"""Entrypoint do CLI `sk` da plataforma smarkee."""

from typing import Annotated

import typer

from sk import output
from sk.command_app import SkTyper
from sk.commands.account import account_app
from sk.commands.auth import auth_app
from sk.commands.bsm import bsm_app
from sk.commands.config import config_app
from sk.commands.ipm import ipm_app
from sk.commands.sum import sum_app
from sk.help import option

app = SkTyper(
    name="sk",
    help="Smarkee Platform Command Line Interface (CLI).",
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    # Explícito: mostrar variáveis locais em erros exporia tokens.
    pretty_exceptions_show_locals=False,
)


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
) -> None:
    # Grava o modo a cada execução, inclusive o padrão, para um estado não vazar para a seguinte.
    output.configure(raw=raw, output_format=output_format)


app.add_typer(auth_app, name="auth")
app.add_typer(config_app, name="config")
app.add_typer(ipm_app, name="ipm")
app.add_typer(bsm_app, name="bsm")
app.add_typer(sum_app, name="sum")
app.add_typer(account_app, name="account")


def main() -> None:
    app()
