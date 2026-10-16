"""Entrypoint do CLI `sk` da plataforma smarkee."""

import typer

from sk.commands.auth import auth_app
from sk.commands.config import config_app
from sk.commands.register import REGISTER_HELP, register_command
from sk.commands.sum import sum_app

app = typer.Typer(
    name="sk",
    help="Smarkee Platform Command Line Interface (CLI).",
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    # Explícito: mostrar variáveis locais em erros exporia tokens.
    pretty_exceptions_show_locals=False,
)
app.add_typer(auth_app, name="auth")
app.add_typer(config_app, name="config")
app.add_typer(sum_app, name="sum")
app.command("register", help=REGISTER_HELP)(register_command)


def main() -> None:
    app()
