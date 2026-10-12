"""Conexão do relay com o SSOT, com o papel do tipo (`docs/POSTGRESQL.md` §14.2).

A conexão do relay é dedicada e direta (sem *pooling* de transação), porque a trava consultiva
é de sessão (`docs/POSTGRESQL.md` §11.4).
"""

from psycopg.conninfo import make_conninfo

from ipm_organization_relay.settings import DatabaseSettings


def conninfo(settings: DatabaseSettings) -> str:
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=settings.name,
        user=settings.user,
        password=settings.password.get_secret_value() if settings.password is not None else None,
    )
