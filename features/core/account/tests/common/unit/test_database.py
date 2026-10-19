"""Conexão com o SSOT: informação de conexão e parâmetros do pool (sem banco)."""

from typing import Any, ClassVar

import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import SecretStr

from core_account.common import database
from core_account.common.settings import DatabaseSettings


def settings(password: str | None = None) -> DatabaseSettings:
    return DatabaseSettings(
        user="core_account_x_login", password=SecretStr(password) if password else None
    )


def test_conninfo_carries_the_login_role_and_the_secret_only_when_there_is_one() -> None:
    info = conninfo_to_dict(database.conninfo(settings("segredo")))
    assert (info["user"], info["dbname"], info["password"]) == (
        "core_account_x_login",
        "smarkee",
        "segredo",
    )
    assert "password" not in conninfo_to_dict(database.conninfo(settings()))


class FakePool:
    created: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, conninfo: str, **options: Any) -> None:
        FakePool.created.append(options)

    async def open(self, **options: Any) -> None: ...


@pytest.mark.parametrize(
    ("row_factory", "expected"),
    [(None, {"autocommit": True}), (dict_row, {"autocommit": True, "row_factory": dict_row})],
)
async def test_the_pool_is_autocommit_and_takes_an_optional_row_factory(
    monkeypatch: pytest.MonkeyPatch, row_factory: Any, expected: dict[str, Any]
) -> None:
    FakePool.created.clear()
    monkeypatch.setattr(database, "AsyncConnectionPool", FakePool)
    await database.open_pool(settings(), row_factory=row_factory)
    assert FakePool.created[0]["kwargs"] == expected
