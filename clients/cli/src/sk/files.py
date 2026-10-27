"""Leitura e gravação de arquivos locais do sk (configuração, credenciais e chaves)."""

import os
import sys
import tempfile
from pathlib import Path

STANDARD_INPUT = Path("-")
"""Caminho que, numa opção que lê um arquivo, quer dizer a entrada padrão (como em `cat -`)."""

MAXIMUM_STANDARD_INPUT_BYTES = 64 * 1024
"""Teto da leitura da entrada padrão: uma entrada sem fim não pode consumir a memória."""


class StandardInputError(Exception):
    """A entrada padrão não pôde ser lida (é um terminal, está vazia ou passa do teto)."""


def read_standard_input() -> bytes:
    """Lê toda a entrada padrão, que precisa vir de um pipe ou redirecionamento.

    Num terminal interativo a leitura esperaria a pessoa digitar sem aviso: falha de imediato.
    O conteúdo nunca entra na mensagem de erro.
    """
    if sys.stdin.isatty():
        raise StandardInputError("standard input is a terminal: pipe the content into the command")
    content = sys.stdin.buffer.read(MAXIMUM_STANDARD_INPUT_BYTES + 1)
    if len(content) > MAXIMUM_STANDARD_INPUT_BYTES:
        raise StandardInputError(
            f"standard input is larger than {MAXIMUM_STANDARD_INPUT_BYTES // 1024} KiB"
        )
    if not content.strip():
        raise StandardInputError("standard input is empty")
    return content


def write_private_file(path: Path, content: str) -> None:
    """Grava o arquivo de forma atômica, com permissão 0600 e diretório 0700 quando criado.

    O conteúdo vai para um arquivo temporário no mesmo diretório, que substitui o destino
    por `os.replace`: uma interrupção no meio da escrita não deixa o arquivo truncado.
    Levanta `OSError` em caso de falha, sem deixar o arquivo temporário para trás.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkstemp cria o arquivo com permissão 0600.
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def create_private_file(path: Path, content: str) -> None:
    """Cria um arquivo exclusivamente (recusa sobrescrever), com permissão 0600."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as target_file:
            target_file.write(content)
            target_file.flush()
            os.fsync(target_file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
