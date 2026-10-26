"""Modo de saída da execução do `sk` (decisão 0093): `--raw` e `--output`.

O callback raiz grava o modo a cada invocação, inclusive o padrão, para que um estado não vaze de
uma execução para a seguinte (por exemplo, entre testes que usam o mesmo processo). Este módulo
também limpa o texto que vem de fora (API, arquivo) antes de ele chegar ao terminal e monta o
documento JSON.
"""

import dataclasses
import enum
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast


class OutputFormat(enum.StrEnum):
    """Formato do resultado: `table` (painel e tabela, padrão) ou `json` (documento único)."""

    TABLE = "table"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class OutputMode:
    """Como a execução atual apresenta o resultado."""

    raw: bool = False
    format: OutputFormat = OutputFormat.TABLE


_mode = OutputMode()

# Sequências de escape: OSC (`ESC ]` até BEL ou `ESC \`), CSI (`ESC [`) e as demais de dois bytes.
_ESCAPE_SEQUENCE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-?]*[ -/]*[@-~]?|\x1b[@-Z\\-_]?"
)
# Controles C0 (menos TAB e LF) e C1: não têm significado em texto e comandam o terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_LINE_BREAKS = re.compile(r"[\t\n]+")
# O JSON escapa os controles C0, mas não o DEL nem os C1: eles seguem escapados à mão.
_JSON_UNESCAPED_CONTROL = re.compile(r"[\x7f-\x9f]")


def configure(*, raw: bool, output_format: OutputFormat = OutputFormat.TABLE) -> None:
    """Define o modo da execução. Chamado pelo callback raiz, a cada invocação."""
    # Estado da execução: a CLI processa um comando por vez.
    global _mode
    _mode = OutputMode(raw=raw, format=output_format)


def is_raw() -> bool:
    return _mode.raw


def is_json() -> bool:
    return _mode.format is OutputFormat.JSON


def sanitize(text: str) -> str:
    """Remove sequências de escape e caracteres de controle (menos TAB e quebra de linha).

    Um nome ou descrição vindo do servidor não pode mudar o título do terminal, mover o cursor
    nem esconder texto. A limpeza vale em todos os modos.
    """
    return _CONTROL.sub("", _ESCAPE_SEQUENCE.sub("", text))


def flatten(text: str) -> str:
    """Texto de uma célula em linha única: sem escapes, e TAB e quebra de linha viram espaço.

    É o que impede um valor de desalinhar uma linha de TSV.
    """
    return _LINE_BREAKS.sub(" ", sanitize(text)).strip()


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


def to_data(value: Any) -> Any:
    """Dado de um resultado para o JSON: dataclass vira objeto com chaves camelCase (os nomes da
    API), e tupla vira lista. Quem chama passa só modelos sem campo sensível."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {_camel(f.name): to_data(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [to_data(item) for item in cast(Sequence[Any], value)]
    if isinstance(value, dict):
        return {str(key): to_data(item) for key, item in cast(dict[Any, Any], value).items()}
    return value


def emit(data: Any) -> None:
    """Escreve o documento JSON do resultado na saída padrão: com indentação, ou compacto em
    `--raw`. É o único documento da execução."""
    text = json.dumps(to_data(data), ensure_ascii=False, indent=None if _mode.raw else 2)
    escaped = _JSON_UNESCAPED_CONTROL.sub(lambda m: f"\\u{ord(m.group()):04x}", text)
    sys.stdout.write(escaped + "\n")
