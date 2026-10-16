"""Remoção da conta (`core.account`): o SUM apaga as ligações do dono (decisão 0044).

A conta só é apagada sem serviço habilitado (decisão 0040), então as ligações que sobram estão
desabilitadas e apontam para um dono que não existe mais. Cada módulo apaga o que é seu: o SUM reage
ao `updated` com `removed` da conta, em vez de o `core` escrever no SSOT do SUM. O histórico de
Operations segue a prática dos demais módulos e fica.
"""

from typing import Any

from psycopg import AsyncConnection


async def remove_links_of(conn: AsyncConnection[Any], owner_account_id: str) -> int:
    """Apaga as ligações do dono. Idempotente: repetir não tem efeito. Devolve quantas apagou."""
    cursor = await conn.execute(
        "DELETE FROM sum.service WHERE owner_account_id = %s", (owner_account_id,)
    )
    return cursor.rowcount
