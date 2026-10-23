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
    "account": Tables(
        resource=sql.Identifier("bsm", "account"),
        operation=sql.Identifier("bsm", "account_operation"),
        action_result=sql.Identifier("bsm", "account_action_result"),
        outbox=sql.Identifier("bsm", "account_outbox"),
    ),
}


def tables_of(resource_type: str) -> Tables:
    return _TABLES[resource_type]
