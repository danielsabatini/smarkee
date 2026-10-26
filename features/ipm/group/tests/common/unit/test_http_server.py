"""Servidor HTTP do Receiver: sobe, atende e para quando o papel pede a parada."""

import asyncio
import socket
from typing import Any

import httpx

from ipm_group.common.http.server import serve_http


async def application(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_the_server_answers_requests_and_stops_when_the_role_asks() -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(serve_http(application, host="127.0.0.1", port=0, stop=stop))
    await asyncio.sleep(0.2)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_the_server_answers_on_a_free_port() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    stop = asyncio.Event()
    task = asyncio.create_task(serve_http(application, host="127.0.0.1", port=port, stop=stop))
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/")
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.05)
            else:
                raise AssertionError("o servidor não subiu")
        assert response.status_code == 204
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)
