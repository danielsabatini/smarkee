"""Padrão dos textos de ajuda do `sk`.

Todo comando descreve, na descrição, como o valor é resolvido. Toda opção segue o formato:

    <descrição> [Tipo] [env VARIÁVEL | arquivo SEÇÃO CHAVE | padrão VALOR] [obrigatório|opcional]

    --issuer  URL do OIDC. [String] [env SK_AUTH_ISSUER | arquivo [auth] issuer] [obrigatório]

O bloco de fontes só lista as que existem para a opção; sem nenhuma, ele é omitido. Cada segmento
tem uma cor (tipo, fontes e situação). Os colchetes do formato são escapados para o Rich não os
tratar como tags, e os colchetes dos próprios valores também.
"""

# Cores de cada segmento da opção, em nomes do Rich.
COLOR_TYPE = "cyan"
COLOR_SOURCES = "yellow"
COLOR_REQUIRED = "red"
COLOR_OPTIONAL = "magenta"

ORDER_WITH_FILE = (
    "parâmetro → variável de ambiente → arquivo de configuração (config.toml) → padrão"
)
ORDER_WITHOUT_FILE = (
    "parâmetro → variável de ambiente → padrão (o arquivo que será criado não é lido)"
)


def _escape(text: str) -> str:
    return text.replace("[", "\\[")


def _segment(text: str, color: str) -> str:
    # O "[" de abertura também é escapado: "[obrigatório]" sem escape seria uma tag do Rich.
    return f"[{color}]\\[{_escape(text)}][/]"


def command(description: str, *, order: str = ORDER_WITH_FILE) -> str:
    """Descrição de um comando: o que faz e a ordem de resolução dos valores."""
    return _escape(f"{description}\n\nOrdem de resolução: {order}.")


def option(
    description: str,
    *,
    kind: str,
    variable: str | None,
    file: str | None,
    default: str,
) -> str:
    """Características de uma opção, no formato:

    <descrição> [Tipo] [env VARIÁVEL | arquivo SEÇÃO CHAVE | padrão VALOR] [obrigatório|opcional]

    Só as fontes que existem são listadas; sem nenhuma, o bloco é omitido. A situação deriva do
    padrão: sem padrão ("nenhum"), a opção é obrigatória e precisa ser informada por uma das
    fontes; com padrão, é opcional. Os segmentos são marcados com markup do Rich. Os colchetes são
    escapados: sem isso, o Rich leria "[obrigatório]" ou "[String]" como tags, e não como texto.
    """
    sources: list[str] = []
    if variable:
        sources.append(f"env {variable}")
    if file:
        sources.append(f"arquivo {file}")
    if default != "nenhum":
        sources.append(f"padrão {default}")
    if default == "nenhum":
        status = _segment("obrigatório", COLOR_REQUIRED)
    else:
        status = _segment("opcional", COLOR_OPTIONAL)
    segments = [_escape(description), _segment(kind, COLOR_TYPE)]
    if sources:
        segments.append(_segment(" | ".join(sources), COLOR_SOURCES))
    segments.append(status)
    return " ".join(segments)
