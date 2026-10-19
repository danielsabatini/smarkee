"""Dependências do Receiver HTTP, montadas pelo `main.py` e trocadas nos testes."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core_account.common.ids import new_identifier, utc_now
from core_account.common.ports import Publisher
from core_account.receiver.domain.principal import Principal
from core_account.receiver.domain.ratelimit import SlidingWindowLimiter
from core_account.receiver.http.ports import AttachedResources, Repository
from core_account.receiver.settings import ApiSettings


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    settings: ApiSettings
    authenticator: Authenticator
    repository: Repository
    publisher: Publisher
    limiter: SlidingWindowLimiter
    resources: AttachedResources
    is_ready: Callable[[], bool] = lambda: True
    """Prontidão das dependências críticas (NATS); usada por `/health/ready`."""
    clock: Callable[[], datetime] = utc_now
    identifiers: Callable[[], str] = new_identifier
