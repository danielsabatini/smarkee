"""Motor de planejamento e execução da retenção de dados."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from smarkee_dev_retention.adapters import RetentionDatabase
from smarkee_dev_retention.model import TARGET_TABLES, TargetTable


@dataclass(frozen=True, slots=True)
class PurgeItem:
    """Resultado do cálculo de expurgo de uma tabela."""

    target: TargetTable
    count: int


def filter_targets(
    targets: Sequence[TargetTable] = TARGET_TABLES,
    module: str | None = None,
    resource_type: str | None = None,
    table_kind: str | None = None,
) -> list[TargetTable]:
    """Filtra as tabelas alvo por módulo, tipo de recurso ou tipo de tabela."""
    filtered: list[TargetTable] = []
    for t in targets:
        if module and t.module != module:
            continue
        if resource_type and t.resource_type != resource_type:
            continue
        if table_kind and t.table_kind != table_kind:
            continue
        filtered.append(t)
    return filtered


def plan_retention(
    db: RetentionDatabase,
    targets: Sequence[TargetTable],
    cutoff: datetime,
) -> list[PurgeItem]:
    """Avalia cada tabela e conta quantos registros seriam expurgados."""
    plan: list[PurgeItem] = []
    for t in targets:
        count = db.count_expired(t, cutoff)
        plan.append(PurgeItem(target=t, count=count))
    return plan


def apply_retention(
    db: RetentionDatabase,
    targets: Sequence[TargetTable],
    cutoff: datetime,
) -> list[PurgeItem]:
    """Executa o expurgo efetivo em cada tabela."""
    results: list[PurgeItem] = []
    for t in targets:
        purged = db.purge_expired(t, cutoff)
        results.append(PurgeItem(target=t, count=purged))
    return results
