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
    # Em terminal interativo, aproveita a largura do terminal (mínimo DEFAULT_WIDTH);
    # em pipes/testes (não-tty), fixa em DEFAULT_WIDTH para estabilidade.
    import shutil
    import sys

    stream = sys.stderr if stderr else sys.stdout
    if stream.isatty():
        width = max(shutil.get_terminal_size().columns, DEFAULT_WIDTH)
    else:
        width = DEFAULT_WIDTH
    return Console(stderr=stderr, highlight=False, width=width)


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


def table(
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[str | Text]],
    *,
    style: str = "green",
    wrap: Sequence[str] = (),
) -> None:
    """Tabela de sucesso (saída padrão), no mesmo painel do `panel`, com uma linha por registro.

    Uma célula pode ser um `Text` com estilo (por exemplo, o estado em verde ou amarelo). As colunas
    em `wrap` quebram linha quando a tabela não cabe; as demais ficam inteiras. Sem nenhuma, a
    largura acaba cortando todas, inclusive os identificadores que o usuário precisa copiar.
    """
    grid = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="bold dim")
    for column in columns:
        grid.add_column(column, overflow="fold", no_wrap=column not in wrap)
    for row in rows:
        grid.add_row(*row)
    _console().print(
        Panel(
            grid,
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
    """Erro na saída de erro: painel com borda vermelha, causa e, quando houver, a dica."""
    content = Text(detail)
    if hint:
        content.append(f"\n→ {hint}", style="dim")
    _console(stderr=True).print(
        Panel(
            content,
            title=Text(f"✗ {title}", style="bold red"),
            title_align="left",
            border_style="red",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def warning(text: str) -> None:
    """Aviso na saída de erro: painel com borda amarela e o texto."""
    _console(stderr=True).print(
        Panel(
            Text(text),
            title=Text("! Warning", style="bold yellow"),
            title_align="left",
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


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
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")
