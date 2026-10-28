"""Regras da ligação de serviço aplicadas na admissão síncrona (decisões 0033 e 0098).

Puro: sem banco, rede ou relógio. As regras do catálogo (`enable_desired`, `disable_desired`) são
as de `common/service_rules.py`; aqui ficam só a forma do `desired` na mensagem e a identidade do
par dono + serviço, cuja unicidade é verificada na mesma transação pelo adaptador do SSOT
(`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from typing import Any

from sum_service.common.contracts import generated


def pair_lock_key(owner_account_id: str, service: str) -> str:
    """Chave que serializa as transações que disputam o mesmo par dono + serviço."""
    return f"sum.service.pair:{owner_account_id}:{service}"


def idempotency_lock_key(requested_by: str, key: str) -> str:
    return f"sum.service.idempotency:{requested_by}:{key}"


def message_data(desired: Mapping[str, Any]) -> dict[str, Any]:
    model = generated.ServiceDesiredData.model_validate(desired)
    return model.model_dump(mode="json", exclude_none=True)
