"""Aplica eventos `desired` de `ipm.role` ao catálogo de Roles em memória (decisões 0088 e 0092).

Quem entrega as mensagens é o `StateConsumer` (um consumer por instância, com
`DeliverLastPerSubject`); este módulo só interpreta o envelope.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_group.common.resource import MODULE

logger = logging.getLogger(__name__)


class RoleCatalogWatcher:
    """Mantém o `RolesCatalog` em memória sincronizado com os `desired` de `ipm.role`."""

    def __init__(self, catalog: RolesCatalog) -> None:
        self._catalog = catalog

    async def on_message(self, data: bytes) -> bool:
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid role desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != MODULE
            or envelope.resource_type != "role"
        ):
            return False
        return self._catalog.apply_role_desired(envelope.resource_id, envelope.data)
