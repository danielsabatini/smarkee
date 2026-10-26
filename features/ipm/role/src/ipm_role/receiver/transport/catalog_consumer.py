"""Aplica eventos `desired` de `ipm.permission` ao catálogo de permissões delegáveis (0092).

Quem entrega as mensagens é o `StateConsumer` (um consumer por instância, com
`DeliverLastPerSubject`); este módulo só interpreta o envelope.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ipm_role.common.catalog import GrantableCatalog
from ipm_role.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_role.common.resource import MODULE

logger = logging.getLogger(__name__)


class PermissionCatalogWatcher:
    """Mantém o `GrantableCatalog` sincronizado com os `desired` de `ipm.permission`."""

    def __init__(self, catalog: GrantableCatalog) -> None:
        self._catalog = catalog

    async def on_message(self, data: bytes) -> bool:
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid permission desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != MODULE
            or envelope.resource_type != "permission"
        ):
            return False
        return self._catalog.apply_permission_desired(envelope.resource_id, envelope.data)
