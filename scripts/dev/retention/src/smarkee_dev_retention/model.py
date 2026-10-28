"""Modelos e tipos para a política de retenção do SSOT."""

import re
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class TargetTable:
    """Tabela de outbox ou idempotency com seu papel de manutenção."""

    module: str
    resource_type: str
    schema: str
    table_name: str
    table_kind: str  # "outbox" ou "idempotency"
    maintenance_role: str


TARGET_TABLES: tuple[TargetTable, ...] = (
    TargetTable("core", "account", "core", "account_outbox", "outbox", "core_maintenance_login"),
    TargetTable(
        "core", "account", "core", "account_idempotency", "idempotency", "core_maintenance_login"
    ),
    TargetTable("bsm", "account", "bsm", "account_outbox", "outbox", "bsm_maintenance_login"),
    TargetTable(
        "bsm", "account", "bsm", "account_idempotency", "idempotency", "bsm_maintenance_login"
    ),
    TargetTable(
        "sum", "service", "sum", "service_outbox", "outbox", "sum_service_maintenance_login"
    ),
    TargetTable(
        "sum",
        "service",
        "sum",
        "service_idempotency",
        "idempotency",
        "sum_service_maintenance_login",
    ),
    TargetTable("ipm", "permission", "ipm", "permission_outbox", "outbox", "ipm_maintenance_login"),
    TargetTable(
        "ipm",
        "permission",
        "ipm",
        "permission_idempotency",
        "idempotency",
        "ipm_maintenance_login",
    ),
    TargetTable("ipm", "role", "ipm", "role_outbox", "outbox", "ipm_maintenance_login"),
    TargetTable("ipm", "role", "ipm", "role_idempotency", "idempotency", "ipm_maintenance_login"),
    TargetTable("ipm", "group", "ipm", "group_outbox", "outbox", "ipm_maintenance_login"),
    TargetTable("ipm", "group", "ipm", "group_idempotency", "idempotency", "ipm_maintenance_login"),
    TargetTable(
        "ipm", "organization", "ipm", "organization_outbox", "outbox", "ipm_maintenance_login"
    ),
    TargetTable(
        "ipm",
        "organization",
        "ipm",
        "organization_idempotency",
        "idempotency",
        "ipm_maintenance_login",
    ),
    TargetTable("ipm", "user", "ipm", "user_outbox", "outbox", "ipm_maintenance_login"),
    TargetTable("ipm", "user", "ipm", "user_idempotency", "idempotency", "ipm_maintenance_login"),
    TargetTable(
        "ipm", "serviceaccount", "ipm", "serviceaccount_outbox", "outbox", "ipm_maintenance_login"
    ),
    TargetTable(
        "ipm",
        "serviceaccount",
        "ipm",
        "serviceaccount_idempotency",
        "idempotency",
        "ipm_maintenance_login",
    ),
)


def parse_duration(duration_str: str) -> timedelta:
    """Converte strings no formato 24h, 30m, 60s, 7d ou 0s em timedelta."""
    text = duration_str.strip().lower()
    if text in ("0", "0s", "0m", "0h", "0d"):
        return timedelta(seconds=0)

    match = re.fullmatch(r"(\d+)\s*([smhd])", text)
    if not match:
        msg = f"Formato de duração inválido: '{duration_str}'. Use ex: 24h, 30m, 60s, 7d, 0s."
        raise ValueError(msg)

    value, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    msg = f"Unidade de tempo desconhecida: '{unit}'"
    raise ValueError(msg)
