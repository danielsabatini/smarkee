"""Motor de planejamento e execução da republicação."""

from collections.abc import Sequence

from smarkee_dev_republish.adapters import NatsBus, PostgresSsot
from smarkee_dev_republish.model import ALL_KINDS, DesiredRecord, Kind


def select_kinds(
    kinds: Sequence[Kind] = ALL_KINDS,
    module: str | None = None,
    resource_type: str | None = None,
) -> list[Kind]:
    """Filtra os kinds suportados pelos critérios informados."""
    selected: list[Kind] = []
    for kind in kinds:
        if module and kind.module != module:
            continue
        if resource_type and kind.resource_type != resource_type:
            continue
        selected.append(kind)
    return selected


def build_plan(
    ssot: PostgresSsot,
    kinds: Sequence[Kind],
    resource_id: str | None = None,
) -> dict[Kind, list[DesiredRecord]]:
    """Carrega os recursos a republicar para cada Kind."""
    plan: dict[Kind, list[DesiredRecord]] = {}
    for kind in kinds:
        records = ssot.fetch_records(kind, resource_id=resource_id)
        if records:
            plan[kind] = records
    return plan


async def execute_plan(
    plan: dict[Kind, list[DesiredRecord]],
    target: str,
    ssot: PostgresSsot,
    nats_bus: NatsBus | None = None,
) -> dict[str, int]:
    """Executa a republicação no destino escolhido."""
    results: dict[str, int] = {}
    for kind, records in plan.items():
        key = f"{kind.module}.{kind.resource_type}"
        if target == "outbox":
            count = ssot.enqueue_outbox(kind, records)
            results[key] = count
        elif target == "nats":
            if nats_bus is None:
                raise ValueError("NatsBus é obrigatório para target='nats'")
            published = 0
            for record in records:
                if await nats_bus.publish_record(record):
                    published += 1
            results[key] = published
        else:
            raise ValueError(f"Target desconhecido: {target}")
    return results
