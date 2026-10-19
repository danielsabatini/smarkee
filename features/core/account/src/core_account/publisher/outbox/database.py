"""Conexão do Publisher com o SSOT, com o papel de leitura do outbox (`docs/POSTGRESQL.md` §14.2).

A conexão é dedicada e direta (sem *pooling* de transação), porque a trava consultiva é de sessão
(§11.4). Os parâmetros de sessão vêm do papel de login (§14.3).
"""

from psycopg.conninfo import make_conninfo

from core_account.publisher.settings import DatabaseSettings


def conninfo(settings: DatabaseSettings) -> str:
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=settings.name,
        user=settings.user,
        password=settings.password.get_secret_value() if settings.password is not None else None,
    )
