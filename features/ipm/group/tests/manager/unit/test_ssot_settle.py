"""Testes unitários de liquidação de operações no SSOT de ipm.group (decisão 0091).

Caracteriza a regra de transição para o estado `superseded` de operações
pertencentes a gerações anteriores ainda em aberto.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ipm_group.manager.store.ssot import SsotStore
from ipm_group.manager.store.tables import tables_of


@pytest.mark.asyncio
async def test_settle_operations_marks_prior_generations_as_superseded() -> None:
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()

    tables = tables_of("group")
    store = SsotStore(fake_conn, tables)

    # Liquidação quando convergiu (generation=3, converged=True)
    await store.settle_operations("grp-123", generation=3, converged=True)

    assert fake_conn.execute.call_count == 2

    # Primeira chamada: atualiza operações abertas de gerações anteriores para 'superseded'
    first_call_sql, first_call_params = fake_conn.execute.call_args_list[0].args
    sql_text_1 = first_call_sql.as_string()
    assert "operation_status = 'superseded'" in sql_text_1
    assert "desired_generation < %s" in sql_text_1
    assert first_call_params == ("grp-123", 3)

    # Segunda chamada: atualiza operações da geração atual para 'completed'
    second_call_sql, second_call_params = fake_conn.execute.call_args_list[1].args
    sql_text_2 = second_call_sql.as_string()
    assert "operation_status = %s" in sql_text_2
    assert "desired_generation = %s" in sql_text_2
    assert second_call_params == ("completed", True, "grp-123", 3)


@pytest.mark.asyncio
async def test_settle_operations_sets_in_progress_when_not_converged() -> None:
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()

    tables = tables_of("group")
    store = SsotStore(fake_conn, tables)

    # Liquidação quando ainda não convergiu (generation=2, converged=False)
    await store.settle_operations("grp-456", generation=2, converged=False)

    assert fake_conn.execute.call_count == 2
    second_call_params = fake_conn.execute.call_args_list[1].args[1]
    assert second_call_params == ("in_progress", False, "grp-456", 2)
