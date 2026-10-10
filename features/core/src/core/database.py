"""Conexões com o SSOT, uma por papel (`docs/POSTGRESQL.md` §14.2).

Cada serviço lógico usa o seu papel de login, com os privilégios mínimos. Os parâmetros de
sessão (`search_path`, timeouts) vêm do papel (§14.3). As conexões são `autocommit`: toda
gravação do Manager abre a sua transação explícita (`connection.transaction()`).
"""

from typing import Any, Literal, cast

from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from core.settings import DatabaseSettings

Role = Literal[
    "organization_manager",
    "organization_api",
    "user_manager",
    "user_api",
    "relay",
]


def conninfo(settings: DatabaseSettings, role: Role) -> str:
    password = getattr(settings, f"{role}_password")
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=settings.name,
        user=cast("str", getattr(settings, f"{role}_user")),
        password=password.get_secret_value() if password is not None else None,
    )


async def open_pool(
    settings: DatabaseSettings, role: Role, *, max_size: int = 5
) -> AsyncConnectionPool[Any]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo(settings, role),
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open(wait=True, timeout=10.0)
    return pool
