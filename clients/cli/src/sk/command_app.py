"""`SkTyper`: o Typer do `sk`, com a negação por padrão de `--output json` (decisão 0093).

Um comando só aceita `--output json` se declarar `structured=True`, o que diz que ele devolve um
documento JSON (e só um) na saída padrão. Os demais recusam o formato **antes de executar**: sem
isso, `sk --output json ipm role create` criaria o recurso e só então falharia ao imprimir.
"""

import functools
from collections.abc import Callable
from typing import Any

import typer
from typer.core import TyperCommand, TyperGroup, TyperOption

from sk import output, ui

EXIT_USAGE_ERROR = 2


def _hide_typer_default(command: TyperCommand | TyperGroup) -> None:
    """Desliga o `[default: …]` que o Typer acrescenta a cada opção com padrão.

    O texto de ajuda de `sk.help.option` já traz `[default …]`: sem isto, o padrão apareceria duas
    vezes. Opções com `show_default` textual são deixadas como estão.
    """
    for param in command.params:
        if isinstance(param, TyperOption) and not isinstance(param.show_default, str):
            param.show_default = False


class SkCommand(TyperCommand):
    """Comando cujas opções não repetem o padrão que o texto de ajuda já informa."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _hide_typer_default(self)


class SkGroup(TyperGroup):
    """Grupo (com opções próprias, como as da raiz) sem o padrão repetido."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _hide_typer_default(self)


class SkTyper(typer.Typer):
    """`typer.Typer` cujo `command` recebe `structured` (padrão `False`)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("cls", SkGroup)
        super().__init__(*args, **kwargs)

    def command(  # type: ignore[override]
        self, name: str | None = None, *, structured: bool = False, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        kwargs.setdefault("cls", SkCommand)
        register = super().command(name, **kwargs)

        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(function)
            def guarded(*args: Any, **options: Any) -> Any:
                if output.is_json() and not structured:
                    ui.error(
                        "Output format not supported",
                        "This command has no structured output yet.",
                        hint="Repeat the command without --output json.",
                    )
                    raise typer.Exit(EXIT_USAGE_ERROR)
                return function(*args, **options)

            register(guarded)
            return function

        return decorator
