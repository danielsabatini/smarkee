"""Padrão dos textos de ajuda do `sk`.

Todo comando descreve, na descrição, como o valor é resolvido. Toda opção segue o formato:

    <descrição> [Type] [env VARIABLE | file SECTION KEY | default VALUE] [required|optional]

    --timeout  Seconds to wait. [Integer] [default 60] [optional]

O bloco de fontes só lista as que existem para a opção; sem nenhuma, ele é omitido. Cada segmento
tem uma cor (tipo, fontes e situação). Os colchetes do formato são escapados para o Rich não os
tratar como tags, e os colchetes dos próprios valores também.
"""

# Cores de cada segmento da opção, em nomes do Rich.
COLOR_TYPE = "cyan"
COLOR_SOURCES = "yellow"
COLOR_REQUIRED = "red"
COLOR_OPTIONAL = "magenta"

ORDER_WITH_FILE = "environment variable → configuration file (config.toml) → production default"
ORDER_WITHOUT_FILE = (
    "environment variable → production default (the file about to be created is not read)"
)


def _escape(text: str) -> str:
    return text.replace("[", "\\[")


def _segment(text: str, color: str) -> str:
    # O "[" de abertura também é escapado: "[required]" sem escape seria uma tag do Rich.
    return f"[{color}]\\[{_escape(text)}][/]"


def command(description: str, *, order: str = ORDER_WITH_FILE) -> str:
    """Descrição de um comando: o que faz e a ordem de resolução dos valores."""
    return _escape(f"{description}\n\nResolution order: {order}.")


def option(
    description: str,
    *,
    kind: str,
    variable: str | None,
    file: str | None,
    default: str,
) -> str:
    """Características de uma opção, no formato:

    <descrição> [Type] [env VARIABLE | file SECTION KEY | default VALUE] [required|optional]

    Só as fontes que existem são listadas; sem nenhuma, o bloco é omitido. A situação deriva do
    padrão: sem padrão ("none"), a opção é obrigatória e precisa ser informada por uma das
    fontes; com padrão, é opcional. Os segmentos são marcados com markup do Rich. Os colchetes são
    escapados: sem isso, o Rich leria "[required]" ou "[String]" como tags, e não como texto.
    """
    sources: list[str] = []
    if variable:
        sources.append(f"env {variable}")
    if file:
        sources.append(f"file {file}")
    if default != "none":
        sources.append(f"default {default}")
    if default == "none":
        status = _segment("required", COLOR_REQUIRED)
    else:
        status = _segment("optional", COLOR_OPTIONAL)
    segments = [_escape(description), _segment(kind, COLOR_TYPE)]
    if sources:
        segments.append(_segment(" | ".join(sources), COLOR_SOURCES))
    segments.append(status)
    return " ".join(segments)
