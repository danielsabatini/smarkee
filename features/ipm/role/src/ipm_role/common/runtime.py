"""Ciclo de vida de um papel em execução: conexão, saúde, tarefas e encerramento (decisão 0063).

Todo `main.py` repete a mesma sequência: tratar os sinais, conectar ao broker, registrar a saúde,
criar as tarefas, supervisioná-las e, ao sair, drenar a conexão e fechar os demais recursos. Aqui
ela é escrita uma vez; o papel só monta as suas tarefas:

    async with role_runtime(settings.messaging, name="ipm-role-reconciler") as runtime:
        reconciler = Reconciler(StreamPublisher(runtime.stream), settings.loop)
        runtime.start("periodic", periodic_reevaluation(reconciler, ...))
        logger.info("reconciler started")
        return await runtime.serve(health_port=settings.health.port)

O encerramento acontece mesmo quando a montagem falha no meio: a conexão é drenada e os recursos
registrados em `close_after` são fechados, na ordem inversa do registro.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from nats.js import JetStreamContext

from ipm_role.common.http.health import Health, serve_health
from ipm_role.common.lifecycle import stop_on_signals, supervise
from ipm_role.common.messaging import MessagingClient, connect, stream_of
from ipm_role.common.settings import MessagingSettings

logger = logging.getLogger(__name__)


class RoleRuntime:
    """O que um papel em execução compartilha entre as suas tarefas."""

    def __init__(self, client: MessagingClient, stop: asyncio.Event) -> None:
        self.client = client
        self.stream: JetStreamContext = stream_of(client)
        self.stop = stop
        """Pedido de parada (sinal do sistema ou fim inesperado de uma tarefa)."""
        self.health = Health()
        self.health.add_check("nats", lambda: client.is_connected)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closers: list[Callable[[], Awaitable[None]]] = []

    def start(self, name: str, work: Coroutine[Any, Any, None]) -> None:
        """Cria a tarefa `name`; ela é supervisionada a partir de `serve`."""
        if name in self._tasks:
            work.close()
            raise ValueError(f"task {name} already started")
        self._tasks[name] = asyncio.create_task(work)

    def close_after(self, closer: Callable[[], Awaitable[None]]) -> None:
        """Fecha um recurso depois de drenar a conexão (por exemplo, o pool do banco)."""
        self._closers.append(closer)

    async def serve(self, *, health_port: int | None) -> int:
        """Sobe as probes (se o papel não as serve de outro modo) e supervisiona até a parada.

        Devolve o código de saída de `supervise`: 0 na parada pedida, 1 se uma tarefa terminou.
        """
        if health_port is not None:
            self.start("health", serve_health(self.health, health_port, self.stop))
        self.health.mark_started()
        return await supervise(self._tasks, self.stop)

    async def close(self) -> None:
        """Drena a conexão e fecha os recursos, na ordem inversa do registro."""
        try:
            await self.client.drain()
        except Exception as error:  # o encerramento segue: os demais recursos ainda são fechados
            logger.warning("messaging drain failed", exc_info=error)
        for closer in reversed(self._closers):
            try:
                await closer()
            except Exception as error:
                logger.warning("resource close failed", exc_info=error)


@asynccontextmanager
async def role_runtime(settings: MessagingSettings, *, name: str) -> AsyncGenerator[RoleRuntime]:
    """Conecta ao broker com a identidade do papel (`name`) e encerra tudo ao sair."""
    stop = stop_on_signals()
    runtime = RoleRuntime(await connect(settings, name=name), stop)
    try:
        yield runtime
    finally:
        await runtime.close()
