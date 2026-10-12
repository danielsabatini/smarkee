"""Tabelas do SSOT de cada tipo de recurso (`docs/POSTGRESQL.md`)."""

from dataclasses import dataclass

from psycopg import sql


@dataclass(frozen=True, slots=True)
class Tables:
    resource: sql.Identifier
    operation: sql.Identifier
    action_result: sql.Identifier
    outbox: sql.Identifier


# `user` é palavra reservada do PostgreSQL: sql.Identifier cita o nome (core."user").
_TABLES = {
    "user": Tables(
        resource=sql.Identifier("core", "user"),
        operation=sql.Identifier("core", "user_operation"),
        action_result=sql.Identifier("core", "user_action_result"),
        outbox=sql.Identifier("core", "user_outbox"),
    ),
}


def tables_of(resource_type: str) -> Tables:
    return _TABLES[resource_type]
