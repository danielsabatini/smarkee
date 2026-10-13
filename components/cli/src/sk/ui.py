"""Apresentação no terminal do `sk` (Rich, já instalado pelo Typer).

Sucesso vai para a saída padrão e erro para a saída de erro, como antes. Cor e caixas só
aparecem em terminal interativo; `NO_COLOR` é respeitado pelo próprio Rich. Este módulo não
imprime tokens nem segredos: quem chama passa apenas o que pode ser mostrado.
"""

from collections.abc import Sequence
from datetime import datetime

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DEFAULT_WIDTH = 100


def _console(*, stderr: bool = False) -> Console:
    # Criado a cada uso: a saída vigente (inclusive a de testes) é a que vale no momento.
    return Console(stderr=stderr, highlight=False, width=DEFAULT_WIDTH)


def panel(title: str, rows: Sequence[tuple[str, str]], *, style: str = "green") -> None:
    """Painel de sucesso com pares rótulo e valor."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)
    table.add_column(overflow="fold")
    for label, value in rows:
        table.add_row(label, Text(value))
    _console().print(
        Panel(
            table,
            title=Text(f"✓ {title}", style=f"bold {style}"),
            title_align="left",
            border_style=style,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def note(text: str) -> None:
    """Linha de orientação ao usuário, abaixo de um painel."""
    _console().print(Text(text, style="dim"))


def error(title: str, detail: str, *, hint: str | None = None) -> None:
    """Erro na saída de erro: título vermelho, causa e, quando houver, a dica de correção."""
    console = _console(stderr=True)
    console.print(Text(f"✗ {title}", style="bold red"))
    console.print(Text(f"  {detail}"))
    if hint:
        console.print(Text(f"  → {hint}", style="dim"))


def warning(text: str) -> None:
    _console(stderr=True).print(Text(f"! {text}", style="yellow"))


def url_panel(title: str, url: str) -> None:
    """Mostra uma URL para copiar, em destaque, na saída de erro (é um passo interativo)."""
    _console(stderr=True).print(
        Panel(
            Text(url, style="bold cyan", overflow="fold"),
            title=Text(title, style="bold"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def format_expiry(moment: datetime) -> str:
    return moment.astimezone().strftime("%d/%m/%Y %H:%M")
