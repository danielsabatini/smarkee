"""Servidor HTTP mínimo de saúde do processo (probes do Kubernetes e healthcheck do Compose).

Expõe só três rotas, sem dados de configuração nem de instância (menor superfície, `AGENTS.md`
§4):

- `/health/live`: o laço principal ainda dá sinal de vida. Não consulta dependências externas,
  para uma queda do NATS ou do banco não reiniciar todos os pods.
- `/health/ready`: as dependências críticas registradas estão disponíveis.
- `/health/startup`: a inicialização terminou.

Sem biblioteca HTTP: o protocolo necessário é uma linha de pedido e uma resposta JSON.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 5.0
MAXIMUM_REQUEST_LINE_BYTES = 1024

_REASONS = {200: "OK", 404: "Not Found", 405: "Method Not Allowed", 503: "Service Unavailable"}


class Health:
    """Estado de saúde do processo: sinal de vida, inicialização e verificações de prontidão."""

    def __init__(
        self,
        *,
        stale_after_seconds: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stale_after = stale_after_seconds
        self._monotonic = monotonic
        self._last_beat = monotonic()
        self._started = False
        self._checks: dict[str, Callable[[], bool]] = {}

    def beat(self) -> None:
        """O laço principal chama a cada ciclo; sem isso por tempo demais, o processo está preso."""
        self._last_beat = self._monotonic()

    def mark_started(self) -> None:
        self._started = True

    def add_check(self, name: str, check: Callable[[], bool]) -> None:
        self._checks[name] = check

    def live(self) -> tuple[bool, dict[str, str]]:
        alive = self._monotonic() - self._last_beat <= self._stale_after
        return alive, {"heartbeat": "UP" if alive else "DOWN"}

    def ready(self) -> tuple[bool, dict[str, str]]:
        results = {name: "UP" if check() else "DOWN" for name, check in self._checks.items()}
        return self._started and all(value == "UP" for value in results.values()), results

    def startup(self) -> tuple[bool, dict[str, str]]:
        return self._started, {}


def _response(status: int, body: dict[str, object]) -> bytes:
    payload = json.dumps(body).encode()
    head = (
        f"HTTP/1.1 {status} {_REASONS[status]}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    )
    return head.encode() + payload


def answer(health: Health, method: str, path: str) -> bytes:
    if method != "GET":
        return _response(405, {"status": "DOWN"})
    probes = {
        "/health/live": health.live,
        "/health/ready": health.ready,
        "/health/startup": health.startup,
    }
    probe = probes.get(path)
    if probe is None:
        return _response(404, {"status": "DOWN"})
    healthy, checks = probe()
    status = "UP" if healthy else ("STARTING" if path == "/health/startup" else "DOWN")
    body: dict[str, object] = {"status": status}
    if checks:
        body["checks"] = checks
    return _response(200 if healthy else 503, body)


async def _handle(
    health: Health, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=REQUEST_TIMEOUT_SECONDS)
        parts = line[:MAXIMUM_REQUEST_LINE_BYTES].decode("latin-1").split()
        method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
        writer.write(answer(health, method, path.split("?", 1)[0]))
        await writer.drain()
    except (TimeoutError, ConnectionError, OSError) as error:
        logger.warning("health request failed", exc_info=error)
    finally:
        writer.close()


async def serve_health(health: Health, port: int, stop: asyncio.Event) -> None:
    """Atende as probes até `stop`; escuta em todas as interfaces do contêiner."""
    server = await asyncio.start_server(
        lambda reader, writer: _handle(health, reader, writer),
        host="0.0.0.0",  # noqa: S104 (as probes chegam pelo IP do pod)
        port=port,
    )
    async with server:
        await stop.wait()
