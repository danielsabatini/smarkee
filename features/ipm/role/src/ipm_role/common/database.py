"""Conexão com o SSOT, com o papel de login de cada papel (`docs/data/POSTGRESQL.md` §14.2).

Os parâmetros de sessão (`search_path`, timeouts) vêm do papel de login (§14.3). As conexões do pool
são `autocommit`: toda gravação abre a sua transação explícita (`connection.transaction()`).
"""

from typing import Any

from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from ipm_role.common.settings import DatabaseSettings


def conninfo(settings: DatabaseSettings) -> str:
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=settings.name,
        user=settings.user,
        password=settings.password.get_secret_value() if settings.password is not None else None,
    )


async def open_pool(
    settings: DatabaseSettings, *, max_size: int = 5, row_factory: Any | None = None
) -> AsyncConnectionPool[Any]:
    """Abre o pool. `row_factory` (por exemplo, `dict_row`) vale para todas as conexões."""
    kwargs: dict[str, Any] = {"autocommit": True}
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo(settings),
        min_size=1,
        max_size=max_size,
        kwargs=kwargs,
        # Conexão quebrada (reinício do banco, corte de rede) é descartada ao ser requisitada,
        # em vez de falhar a primeira operação que a usar.
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await pool.open(wait=True, timeout=10.0)
    return pool
