"""Conexão do Manager com o SSOT, com o papel do tipo (`docs/POSTGRESQL.md` §14.2).

A conexão é `autocommit`: a transação de cada pedido é explícita (`connection.transaction()`).
"""

from typing import Any

from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from sum_service_manager.settings import DatabaseSettings


def conninfo(settings: DatabaseSettings) -> str:
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=settings.name,
        user=settings.user,
        password=settings.password.get_secret_value() if settings.password is not None else None,
    )


async def open_pool(settings: DatabaseSettings, *, max_size: int = 5) -> AsyncConnectionPool[Any]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo(settings),
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open(wait=True, timeout=10.0)
    return pool
