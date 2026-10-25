"""Provedor somente leitura do armazenamento de estado em disco do Observer (decisão 0073).

Lê o arquivo `<directory>/<resource_id>.json`. Não escreve nem cria diretórios. Qualquer falha de
I/O ou documento inválido vira `ProviderError`, que o domínio traduz em `presence = unknown`.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from ipm_role.observer.domain.identity import ProviderError
from ipm_role.observer.settings import StorageSettings

_RESOURCE_ID = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")


class StateStoreConnection:
    """Acesso somente leitura aos arquivos JSON de estado da Role."""

    def __init__(self, settings: StorageSettings) -> None:
        if not settings.directory:
            raise ValueError("storage.directory is required")
        self._root = Path(settings.directory).resolve()

    def _path_for(self, resource_id: str) -> Path:
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ProviderError("invalid resource_id")
        candidate = (self._root / f"{resource_id}.json").resolve()
        if candidate.parent != self._root:
            raise ProviderError("invalid resource path")
        return candidate

    def _read_record_sync(self, resource_id: str) -> dict[str, Any] | None:
        path = self._path_for(resource_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ProviderError("failed to read state file") from error
        try:
            document = json.loads(raw)
        except ValueError as error:
            raise ProviderError("invalid JSON in state file") from error
        if not isinstance(document, dict):
            raise ProviderError("state file root is not an object")
        return document  # pyright: ignore[reportUnknownVariableType]

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._read_record_sync, resource_id)
