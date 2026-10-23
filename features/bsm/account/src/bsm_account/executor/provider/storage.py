"""Provedor do armazenamento de estado em disco do Executor (decisão 0073).

Escreve de forma atômica (arquivo temporário no mesmo diretório + `os.replace`) o arquivo
`<directory>/<resource_id>.json`. Falhas de I/O viram `ProviderError`.
"""

import asyncio
import contextlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bsm_account.executor.domain.identity import ProviderError
from bsm_account.executor.settings import StorageSettings

_RESOURCE_ID = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")


class StateStoreConnection:
    """Leitura e escrita atômica dos arquivos JSON de estado da Billing Account."""

    def __init__(self, settings: StorageSettings) -> None:
        if not settings.directory:
            raise ValueError("storage.directory is required")
        self._root = Path(settings.directory).resolve()

    def _path_for(self, resource_id: str) -> Path:
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ProviderError("Rejected", retryable=False, detail="invalid resource_id")
        candidate = (self._root / f"{resource_id}.json").resolve()
        if candidate.parent != self._root:
            raise ProviderError("Rejected", retryable=False, detail="invalid resource path")
        return candidate

    def _read_record_sync(self, resource_id: str) -> dict[str, Any] | None:
        path = self._path_for(resource_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ProviderError(
                "ExternalError", retryable=True, detail="failed to read state file"
            ) from error
        try:
            document = json.loads(raw)
        except ValueError as error:
            raise ProviderError(
                "ExternalError", retryable=False, detail="invalid JSON in state file"
            ) from error
        if not isinstance(document, dict):
            raise ProviderError(
                "ExternalError", retryable=False, detail="state file root is not an object"
            )
        return document  # pyright: ignore[reportUnknownVariableType]

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._read_record_sync, resource_id)

    def _write_record_sync(self, resource_id: str, record: Mapping[str, Any]) -> None:
        path = self._path_for(resource_id)
        payload = json.dumps(dict(record), sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            fd, raw_temp = tempfile.mkstemp(
                prefix=f".{resource_id}.", suffix=".tmp", dir=self._root
            )
            temporary_path = Path(raw_temp)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temporary_path, path)
        except OSError as error:
            if temporary_path is not None:
                with contextlib.suppress(OSError):
                    temporary_path.unlink(missing_ok=True)
            raise ProviderError(
                "ExternalError", retryable=True, detail="failed to write state file"
            ) from error

    async def write_record(self, resource_id: str, record: Mapping[str, Any]) -> None:
        await asyncio.to_thread(self._write_record_sync, resource_id, record)

    def _delete_record_sync(self, resource_id: str) -> None:
        path = self._path_for(resource_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise ProviderError(
                "ExternalError", retryable=True, detail="failed to delete state file"
            ) from error

    async def delete_record(self, resource_id: str) -> None:
        await asyncio.to_thread(self._delete_record_sync, resource_id)
