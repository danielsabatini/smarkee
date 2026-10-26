"""Tabelas do SSOT de cada tipo de recurso (`docs/data/POSTGRESQL.md`)."""

from dataclasses import dataclass

from psycopg import sql


@dataclass(frozen=True, slots=True)
class Tables:
    resource: sql.Identifier
    operation: sql.Identifier
    action_result: sql.Identifier
    outbox: sql.Identifier


# Os nomes de tabela vêm de `sql.Identifier` (core.account), e não de texto montado à mão.
_TABLES = {
    "account": Tables(
        resource=sql.Identifier("core", "account"),
        operation=sql.Identifier("core", "account_operation"),
        action_result=sql.Identifier("core", "account_action_result"),
        outbox=sql.Identifier("core", "account_outbox"),
    ),
}


def tables_of(resource_type: str) -> Tables:
    return _TABLES[resource_type]
