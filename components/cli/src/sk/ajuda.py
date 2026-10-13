"""Padrão dos textos de ajuda do `sk`.

Todo comando descreve, na descrição, como o valor é resolvido. Toda opção segue o formato:

    <descrição> [Tipo] [variável | arquivo | padrão] [obrigatório|opcional]

    --issuer  URL do issuer OIDC. [String] [SK_AUTH_ISSUER | \\[auth] issuer | nenhum] [obrigatório]

Cada segmento tem uma cor (tipo, resolução e situação). Os colchetes do formato são escapados
para o Rich não os tratar como tags, e os colchetes dos próprios valores também.
"""

# Cores de cada segmento da opção, em nomes do Rich.
COR_TIPO = "cyan"
COR_RESOLUCAO = "yellow"
COR_SITUACAO = "magenta"

ORDEM_COM_ARQUIVO = (
    "parâmetro → variável de ambiente → arquivo de configuração (config.toml) → padrão"
)
ORDEM_SEM_ARQUIVO = (
    "parâmetro → variável de ambiente → padrão (o arquivo que será criado não é lido)"
)


def _escapa(texto: str) -> str:
    return texto.replace("[", "\\[")


def _segmento(texto: str, cor: str) -> str:
    # O "[" de abertura também é escapado: "[obrigatório]" sem escape seria uma tag do Rich.
    return f"[{cor}]\\[{_escapa(texto)}][/]"


def comando(descricao: str, *, ordem: str = ORDEM_COM_ARQUIVO) -> str:
    """Descrição de um comando: o que faz e a ordem de resolução dos valores."""
    return _escapa(f"{descricao}\n\nOrdem de resolução: {ordem}.")


def opcao(
    descricao: str,
    *,
    tipo: str,
    variavel: str | None,
    arquivo: str | None,
    padrao: str,
    obrigatorio: bool = False,
) -> str:
    """Características de uma opção, no formato:

    <descrição> [Tipo] [variável | arquivo | padrão] [obrigatório|opcional]

    Os segmentos são marcados com markup do Rich. Os colchetes são escapados: sem isso, o Rich
    leria "[obrigatório]" ou "[String]" como tags, e não como texto.
    """
    resolucao = f"{variavel or 'nenhuma'} | {arquivo or 'nenhum'} | {padrao}"
    situacao = "obrigatório" if obrigatorio else "opcional"
    return (
        f"{_escapa(descricao)} "
        f"{_segmento(tipo, COR_TIPO)} "
        f"{_segmento(resolucao, COR_RESOLUCAO)} "
        f"{_segmento(situacao, COR_SITUACAO)}"
    )
