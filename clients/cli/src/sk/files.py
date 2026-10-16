"""Gravação de arquivos locais do sk (configuração e credenciais)."""

import os
import tempfile
from pathlib import Path


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
