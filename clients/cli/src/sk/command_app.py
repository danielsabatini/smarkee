"""`SkTyper`: o Typer do `sk`, com a negação por padrão de `--output json` (decisão 0093).

Um comando só aceita `--output json` se declarar `structured=True`, o que diz que ele devolve um
documento JSON (e só um) na saída padrão. Os demais recusam o formato **antes de executar**: sem
isso, `sk --output json ipm role create` criaria o recurso e só então falharia ao imprimir.
"""

import functools
from collections.abc import Callable
from typing import Any

import typer

from sk import output, ui

EXIT_USAGE_ERROR = 2


class SkTyper(typer.Typer):
    """`typer.Typer` cujo `command` recebe `structured` (padrão `False`)."""

    def command(  # type: ignore[override]
        self, name: str | None = None, *, structured: bool = False, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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
