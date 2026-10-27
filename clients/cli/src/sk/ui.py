"""Apresentação no terminal do `sk` (Rich, já instalado pelo Typer).

Sucesso vai para a saída padrão e erro para a saída de erro, como antes. Cor e caixas só
aparecem em terminal interativo; `NO_COLOR` é respeitado pelo próprio Rich. Este módulo não
imprime tokens nem segredos: quem chama passa apenas o que pode ser mostrado.
"""

import os
import sys
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sk import output

DEFAULT_WIDTH = 100


def _plain(cell: str | Text) -> str:
    return cell.plain if isinstance(cell, Text) else cell


def _clean(cell: str | Text) -> str | Text:
    """Célula sem escapes nem controles (decisão 0093), preservando o estilo de um `Text`."""
    if isinstance(cell, Text):
        cleaned = cell.copy()
        cleaned.plain = output.sanitize(cell.plain)
        return cleaned
    return output.sanitize(cell)


def _write_lines(lines: Sequence[Sequence[str | Text]]) -> None:
    """Saída `--raw`: uma linha por registro, campos separados por TAB, sem caixa nem cor.

    Escreve direto na saída padrão, fora do Rich, que quebraria linhas e leria colchetes.
    """
    for line in lines:
        sys.stdout.write("\t".join(output.flatten(_plain(cell)) for cell in line) + "\n")


_indicator_visible = False
"""Há um indicador de espera desenhado na linha atual da saída de erro."""

_ERASE_LINE = "\r\x1b[2K"
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _erase_indicator() -> None:
    """Apaga o indicador de espera antes de qualquer outra escrita, para ele não deixar resíduo."""
    global _indicator_visible
    if _indicator_visible:
        sys.stderr.write(_ERASE_LINE)
        sys.stderr.flush()
        _indicator_visible = False


def _console(*, stderr: bool = False) -> Console:
    # Criado a cada uso: a saída vigente (inclusive a de testes) é a que vale no momento.
    # Em terminal interativo, aproveita a largura do terminal (mínimo DEFAULT_WIDTH);
    # em pipes/testes (não-tty), fixa em DEFAULT_WIDTH para estabilidade.
    import shutil
    import sys

    _erase_indicator()
    stream = sys.stderr if stderr else sys.stdout
    if stream.isatty():
        width = max(shutil.get_terminal_size().columns, DEFAULT_WIDTH)
    else:
        width = DEFAULT_WIDTH
    return Console(stderr=stderr, highlight=False, width=width)


def _emit_json(data: Any) -> None:
    """Resultado de `--output json`. Um comando com `structured=True` precisa informar `data`."""
    if data is None:
        raise RuntimeError("command declared structured output but gave no data")
    output.emit(data)


def panel(
    title: str,
    rows: Sequence[tuple[str, str]],
    *,
    style: str = "green",
    data: Any = None,
    interim: bool = False,
) -> None:
    """Painel de sucesso com pares rótulo e valor (em `--raw`, uma linha `rótulo<TAB>valor`).

    Em `--output json` sai `data`, um único documento por execução. `interim` marca o painel que
    precede o resultado (por exemplo, "Creation requested" antes de `--wait`): em JSON ele não sai.
    """
    if output.is_json():
        if not interim:
            _emit_json(data)
        return
    if output.is_raw():
        _write_lines(rows)
        return
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)
    table.add_column(overflow="fold")
    for label, value in rows:
        table.add_row(label, Text(output.sanitize(value)))
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
    data: Any = None,
) -> None:
    """Tabela de sucesso (saída padrão), no mesmo painel do `panel`, com uma linha por registro.

    Uma célula pode ser um `Text` com estilo (por exemplo, o estado em verde ou amarelo). As colunas
    em `wrap` quebram linha quando a tabela não cabe; as demais ficam inteiras. Sem nenhuma, a
    largura acaba cortando todas, inclusive os identificadores que o usuário precisa copiar.

    Em `--raw`, vira TSV: o cabeçalho e uma linha por registro, sem título, caixa nem cor. Em
    `--output json`, sai `data` (a lista de registros).
    """
    if output.is_json():
        _emit_json(data)
        return
    if output.is_raw():
        _write_lines([columns, *rows])
        return
    grid = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="bold dim")
    for column in columns:
        grid.add_column(column, overflow="fold", no_wrap=column not in wrap)
    for row in rows:
        grid.add_row(*(_clean(cell) for cell in row))
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
    """Linha de orientação ao usuário, abaixo de um painel.

    Em `--raw` e em `--output json` vai para a saída de erro: a saída padrão fica só com os dados.
    """
    to_stderr = output.is_raw() or output.is_json()
    _console(stderr=to_stderr).print(Text(output.sanitize(text), style="dim"))


class WaitProgress:
    """Progresso de uma espera (`--wait`), sempre na saída de erro: a saída padrão não é tocada.

    Em terminal, um indicador numa só linha, com o estado e o tempo decorrido, que é apagado antes
    de qualquer outra escrita. Fora de terminal (pipe, arquivo, CI), uma linha por mudança de
    estado, sem repetir o estado que não mudou.
    """

    def __init__(self, timeout: int) -> None:
        self._timeout = timeout
        self._started = time.monotonic()
        self._last_state: str | None = None
        self._frame = 0
        self._interactive = sys.stderr.isatty() and os.environ.get("TERM") != "dumb"

    def update(self, state: str) -> None:
        """Informa o estado observado na leitura mais recente."""
        global _indicator_visible
        elapsed = int(time.monotonic() - self._started)
        text = output.sanitize(state)
        if self._interactive:
            frame = _SPINNER_FRAMES[self._frame % len(_SPINNER_FRAMES)]
            self._frame += 1
            sys.stderr.write(f"{_ERASE_LINE}{frame} {text} · {elapsed} s of {self._timeout} s")
            sys.stderr.flush()
            _indicator_visible = True
        elif text != self._last_state:
            sys.stderr.write(f"waiting: {text} ({elapsed} s of {self._timeout} s)\n")
            sys.stderr.flush()
        self._last_state = text


@contextmanager
def waiting(timeout: int) -> Generator[WaitProgress]:
    """Acompanha uma espera: ao sair, por qualquer caminho (inclusive Ctrl-C), apaga o indicador."""
    progress = WaitProgress(timeout)
    try:
        yield progress
    finally:
        _erase_indicator()


def empty(text: str) -> None:
    """Resultado de uma listagem sem registros: a nota `text`, ou `[]` em `--output json`."""
    if output.is_json():
        output.emit([])
        return
    note(text)


def error(title: str, detail: str, *, hint: str | None = None) -> None:
    """Erro na saída de erro: painel com borda vermelha, causa e, quando houver, a dica."""
    content = Text(output.sanitize(detail))
    if hint:
        content.append(f"\n→ {output.sanitize(hint)}", style="dim")
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
            Text(output.sanitize(text)),
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
