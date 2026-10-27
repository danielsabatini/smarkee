"""Testes unitários da Workqueue de reconciliação."""

import asyncio

import pytest

from ipm_serviceaccount.controller.engine.workqueue import Workqueue


@pytest.mark.asyncio
async def test_add_and_get_processes_item() -> None:
    queue = Workqueue()
    queue.add("res-1")
    assert queue.queue_size == 1

    item = await queue.get()
    assert item == "res-1"
    assert "res-1" in queue.processing_keys
    assert "res-1" not in queue.dirty_keys

    queue.done("res-1")
    assert "res-1" not in queue.processing_keys


@pytest.mark.asyncio
async def test_add_while_processing_marks_dirty_and_requeues_on_done() -> None:
    queue = Workqueue()
    queue.add("res-1")

    item = await queue.get()
    assert item == "res-1"

    # Chegada concorrente enquanto worker processa res-1
    queue.add("res-1")
    assert queue.queue_size == 0
    assert "res-1" in queue.dirty_keys

    # Worker conclui o primeiro ciclo
    queue.done("res-1")
    assert queue.queue_size == 1
    assert "res-1" not in queue.processing_keys

    # Próximo get pega o res-1 pendente
    item2 = await queue.get()
    assert item2 == "res-1"
    queue.done("res-1")
    assert queue.queue_size == 0


@pytest.mark.asyncio
async def test_duplicate_add_does_not_duplicate_in_queue() -> None:
    queue = Workqueue()
    queue.add("res-1")
    queue.add("res-1")
    assert queue.queue_size == 1

    item = await queue.get()
    assert item == "res-1"
    queue.done("res-1")


@pytest.mark.asyncio
async def test_rate_limited_backoff_and_forget() -> None:
    queue = Workqueue(base_backoff_seconds=0.01, jitter_factor=0.0)
    delay1 = queue.add_rate_limited("res-err")
    assert delay1 >= 0.01

    await asyncio.sleep(delay1 + 0.02)
    assert queue.queue_size == 1

    item = await queue.get()
    assert item == "res-err"
    queue.forget("res-err")
    queue.done("res-err")
    queue.close()
