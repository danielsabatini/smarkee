"""Projeção local dos recursos dependentes de cada Organization (decisões 0077, 0094 e 0100).

Substitui as consultas HTTP às APIs de User e ServiceAccount na exclusão de uma Organization.
O `StateConsumer` entrega o último `desired` de cada recurso dependente (`user`, `serviceaccount`,
`group`, `role`), e esta projeção rastreia quais Organizations ainda possuem dependentes ativos.
"""

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from ipm_organization.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

USER_SUBJECT = "manager.desired.ipm.user.>"
SERVICEACCOUNT_SUBJECT = "manager.desired.ipm.serviceaccount.>"
GROUP_SUBJECT = "manager.desired.ipm.group.>"
ROLE_SUBJECT = "manager.desired.ipm.role.>"
"""Subjects do stream `DESIRED` de que a projeção se alimenta."""

DEPENDENT_SUBJECTS = (USER_SUBJECT, SERVICEACCOUNT_SUBJECT, GROUP_SUBJECT, ROLE_SUBJECT)

_DEPENDENT_TYPES = frozenset({"user", "serviceaccount", "group", "role"})
_PRESENT = "present"


class DependentsProjection:
    """Rastreia quais recursos ativos pertencem a cada Organization."""

    def __init__(self, *, on_change: Callable[[str], None] | None = None) -> None:
        self._on_change = on_change
        self._dependents: dict[tuple[str, str], str] = {}
        # organization_id -> contagem de recursos presentes
        self._counts: dict[str, int] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid dependent desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != "ipm"
            or envelope.resource_type not in _DEPENDENT_TYPES
        ):
            return False
        return self.apply(envelope.resource_type, envelope.resource_id, envelope.data)

    def apply(self, resource_type: str, resource_id: str, desired: Mapping[str, Any]) -> bool:
        key = (resource_type, resource_id)
        org_id = desired.get("organizationId")
        lifecycle = desired.get("lifecycle")

        old_org = self._dependents.get(key)
        new_org = org_id if lifecycle == _PRESENT and isinstance(org_id, str) else None

        if old_org == new_org:
            return False

        if old_org is not None:
            c = self._counts.get(old_org, 0) - 1
            if c <= 0:
                self._counts.pop(old_org, None)
            else:
                self._counts[old_org] = c

        if new_org is not None:
            self._dependents[key] = new_org
            self._counts[new_org] = self._counts.get(new_org, 0) + 1
        else:
            self._dependents.pop(key, None)

        if old_org is not None and self._on_change is not None:
            self._on_change(old_org)
        if new_org is not None and new_org != old_org and self._on_change is not None:
            self._on_change(new_org)

        return True

    def has_dependents(self, organization_id: str) -> bool:
        """`True` se a Organization ainda tem recursos dependentes ativos."""
        return self._counts.get(organization_id, 0) > 0

    def count_dependents(self, organization_id: str) -> int:
        """Total de recursos ativos vinculados à Organization."""
        return self._counts.get(organization_id, 0)
