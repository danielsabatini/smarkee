"""Tabelas do SSOT de cada tipo de recurso (`docs/POSTGRESQL.md`)."""

from dataclasses import dataclass

from psycopg import sql


@dataclass(frozen=True, slots=True)
class Tables:
    resource: sql.Identifier
    operation: sql.Identifier
    action_result: sql.Identifier
    outbox: sql.Identifier


_TABLES = {
    "permission": Tables(
        resource=sql.Identifier("ipm", "permission"),
        operation=sql.Identifier("ipm", "permission_operation"),
        action_result=sql.Identifier("ipm", "permission_action_result"),
        outbox=sql.Identifier("ipm", "permission_outbox"),
    ),
}


def tables_of(resource_type: str) -> Tables:
    return _TABLES[resource_type]
