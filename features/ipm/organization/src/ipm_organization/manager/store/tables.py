"""Tabelas do SSOT de cada tipo de recurso (`docs/data/POSTGRESQL.md`)."""

from dataclasses import dataclass

from psycopg import sql


@dataclass(frozen=True, slots=True)
class Tables:
    resource: sql.Identifier
    operation: sql.Identifier
    action_result: sql.Identifier
    outbox: sql.Identifier


_TABLES = {
    "organization": Tables(
        resource=sql.Identifier("ipm", "organization"),
        operation=sql.Identifier("ipm", "organization_operation"),
        action_result=sql.Identifier("ipm", "organization_action_result"),
        outbox=sql.Identifier("ipm", "organization_outbox"),
    ),
}


def tables_of(resource_type: str) -> Tables:
    return _TABLES[resource_type]
