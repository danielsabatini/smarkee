"""Consumidor dos catálogos de `ipm.permission` e `ipm.role` para a API (decisão 0083).

Atualiza o `AccessCatalog` em memória a partir dos eventos `desired` publicados pelos Managers de
`ipm.permission` e `ipm.role`, sem exigir redeploy para novas permissões ou roles.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ipm_serviceaccount.common.catalog import AccessCatalog
from ipm_serviceaccount.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_serviceaccount.common.resource import MODULE

logger = logging.getLogger(__name__)


class CatalogWatcher:
    """Aplica eventos `desired` de `ipm.permission` e `ipm.role` ao `AccessCatalog` em memória."""

    def __init__(self, catalog: AccessCatalog) -> None:
        self._catalog = catalog

    async def on_message(self, data: bytes) -> bool:
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid catalog desired message", exc_info=error)
            return False
        if envelope.message_type.value != "desired" or envelope.module != MODULE:
            return False
        payload = envelope.data
        if envelope.resource_type == "permission":
            return self._catalog.apply_permission_desired(envelope.resource_id, payload)
        if envelope.resource_type == "role":
            return self._catalog.apply_role_desired(envelope.resource_id, payload)
        return False
