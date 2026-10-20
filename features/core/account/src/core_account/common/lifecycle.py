"""Ciclo de vida de um papel: configuração, sinais, supervisão das tarefas e saída (decisão 0063).

Cada papel só monta as suas tarefas; iniciar, supervisionar e encerrar é daqui.
"""

import asyncio
import logging
import signal
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import NoReturn

from pydantic_settings import BaseSettings

from core_account.common.logging_config import configure_logging
from core_account.common.settings import load_settings

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


class InvalidConfigurationError(Exception):
    """A configuração está completa, mas não é válida. `reason` nunca contém segredos."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def stop_on_signals() -> asyncio.Event:
    """Evento que passa a valer quando o processo recebe SIGINT ou SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    return stop


async def supervise(tasks: Mapping[str, asyncio.Task[None]], stop: asyncio.Event) -> int:
    """Espera o sinal de parada ou o fim inesperado de uma tarefa; encerra todas.

    Devolve o código de saída: 0 se só houve o pedido de parada; 1 se alguma tarefa terminou
    sozinha ou falhou. Com a parada pedida, as tarefas terminam junto com o aviso, e isso é o
    encerramento normal, e não um fim inesperado.
    """
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({waiter, *tasks.values()}, return_when=asyncio.FIRST_COMPLETED)
    exit_code = 0
    if not stop.is_set():
        for name, task in tasks.items():
            if task in done:
                exit_code = 1
                logger.error("task stopped unexpectedly", extra={"smarkee.task.name": name})
    stop.set()
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("task failed", extra={"smarkee.task.name": name}, exc_info=result)
            exit_code = 1
    waiter.cancel()
    return exit_code


def start_role[S: BaseSettings](
    role: str,
    settings_type: type[S],
    missing_required: Callable[[S], list[str]],
    run: Callable[[S], Awaitable[int]],
    *,
    validate: Callable[[S], None] | None = None,
    cli_args: Sequence[str] = (),
) -> NoReturn:
    """Entrypoint comum: configura o log do papel, valida a configuração e roda até encerrar.

    `validate`, se houver, confere o que não é só presença (por exemplo, um catálogo em JSON) e
    levanta `InvalidConfigurationError`; o processo sai sem rodar, com o código de configuração
    inválida. `cli_args` são os argumentos da linha de comando (`sys.argv[1:]` do entrypoint).
    """
    configure_logging(role=role)
    settings = load_settings(settings_type, cli_args)
    missing = missing_required(settings)
    if missing:
        logger.error(
            "missing required configuration", extra={"smarkee.config.missing_variables": missing}
        )
        sys.exit(EXIT_INVALID_CONFIGURATION)
    if validate is not None:
        try:
            validate(settings)
        except InvalidConfigurationError as error:
            logger.error("invalid configuration", extra={"smarkee.reason": error.reason})
            sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))
