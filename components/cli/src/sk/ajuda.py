"""Padrão dos textos de ajuda do `sk`.

Todo comando descreve, na descrição, como o valor é resolvido. Toda opção segue o formato:

    <descrição> [Tipo] [env VARIÁVEL | arquivo SEÇÃO CHAVE | padrão VALOR] [obrigatório|opcional]

    --issuer  URL do OIDC. [String] [env SK_AUTH_ISSUER | arquivo [auth] issuer] [obrigatório]

O bloco de fontes só lista as que existem para a opção; sem nenhuma, ele é omitido. Cada segmento
tem uma cor (tipo, fontes e situação). Os colchetes do formato são escapados para o Rich não os
tratar como tags, e os colchetes dos próprios valores também.
"""

# Cores de cada segmento da opção, em nomes do Rich.
COR_TIPO = "cyan"
COR_FONTES = "yellow"
COR_OBRIGATORIO = "red"
COR_OPCIONAL = "magenta"

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
) -> str:
    """Características de uma opção, no formato:

    <descrição> [Tipo] [env VARIÁVEL | arquivo SEÇÃO CHAVE | padrão VALOR] [obrigatório|opcional]

    Só as fontes que existem são listadas; sem nenhuma, o bloco é omitido. A situação deriva do
    padrão: sem padrão ("nenhum"), a opção é obrigatória e precisa ser informada por uma das
    fontes; com padrão, é opcional. Os segmentos são marcados com markup do Rich. Os colchetes são
    escapados: sem isso, o Rich leria "[obrigatório]" ou "[String]" como tags, e não como texto.
    """
    fontes: list[str] = []
    if variavel:
        fontes.append(f"env {variavel}")
    if arquivo:
        fontes.append(f"arquivo {arquivo}")
    if padrao != "nenhum":
        fontes.append(f"padrão {padrao}")
    if padrao == "nenhum":
        situacao = _segmento("obrigatório", COR_OBRIGATORIO)
    else:
        situacao = _segmento("opcional", COR_OPCIONAL)
    segmentos = [_escapa(descricao), _segmento(tipo, COR_TIPO)]
    if fontes:
        segmentos.append(_segmento(" | ".join(fontes), COR_FONTES))
    segmentos.append(situacao)
    return " ".join(segmentos)
