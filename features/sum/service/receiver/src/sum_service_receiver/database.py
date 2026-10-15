"""Conexão do Receiver com o SSOT, com o papel de leitura (`docs/POSTGRESQL.md` §14.2)."""

from typing import Any

from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from sum_service_receiver.settings import DatabaseSettings


async def open_pool(settings: DatabaseSettings, *, max_size: int = 5) -> AsyncConnectionPool[Any]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        make_conninfo(
            host=settings.host,
            port=settings.port,
            dbname=settings.name,
            user=settings.user,
            password=settings.password.get_secret_value()
            if settings.password is not None
            else None,
        ),
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True, timeout=10.0)
    return pool
