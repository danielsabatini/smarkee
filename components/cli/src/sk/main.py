"""Entrypoint do CLI `sk` da plataforma smarkee."""

import typer

from sk.commands.auth import auth_app
from sk.commands.register import register_command

app = typer.Typer(
    name="sk",
    help="Smarkee IT Solutions Command Line Interface (CLI).",
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    # Explícito: mostrar variáveis locais em erros exporia tokens.
    pretty_exceptions_show_locals=False,
)
app.add_typer(auth_app, name="auth")
app.command("register")(register_command)


def main() -> None:
    app()
