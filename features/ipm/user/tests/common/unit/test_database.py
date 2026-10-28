"""Conexão com o SSOT: informação de conexão e parâmetros do pool (sem banco)."""

from typing import Any, ClassVar

import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import SecretStr

from ipm_user.common import database
from ipm_user.common.settings import DatabaseSettings


def settings(password: str | None = None) -> DatabaseSettings:
    return DatabaseSettings(
        host="localhost",
        port=5432,
        name="ssot",
        user="ipm_user_x_login",
        password=SecretStr(password) if password else None,
    )


def test_conninfo_carries_the_login_role_and_the_secret_only_when_there_is_one() -> None:
    info = conninfo_to_dict(database.conninfo(settings("segredo")))
    assert (info["user"], info["dbname"], info["password"]) == (
        "ipm_user_x_login",
        "ssot",
        "segredo",
    )
    assert "password" not in conninfo_to_dict(database.conninfo(settings()))


class FakePool:
    created: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, conninfo: str, **options: Any) -> None:
        FakePool.created.append(options)

    async def open(self, **options: Any) -> None: ...

    @staticmethod
    async def check_connection(connection: Any) -> None: ...


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


async def test_the_pool_checks_a_connection_before_handing_it_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakePool.created.clear()
    monkeypatch.setattr(database, "AsyncConnectionPool", FakePool)
    await database.open_pool(settings())
    assert FakePool.created[0]["check"] is FakePool.check_connection
