import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from core_user_receiver.contracts import generated
from core_user_receiver.domain.errors import unauthorized
from core_user_receiver.domain.principal import Principal
from core_user_receiver.domain.ratelimit import SlidingWindowLimiter
from core_user_receiver.domain.records import OperationRecord, ResourceRecord
from core_user_receiver.http.app import Dependencies, create_app
from core_user_receiver.http.ports import PublishError
from core_user_receiver.settings import ApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER_ROLES = frozenset({"user.get", "user.delete"})
OPERATOR_ROLES = USER_ROLES | {"platform.admin"}


def principal(subject: str, roles: frozenset[str]) -> Principal:
    return Principal(subject=subject, roles=roles, access_token=f"token-{subject}")


PRINCIPALS = {
    "ana": principal("ana", USER_ROLES),
    "bia": principal("bia", USER_ROLES),
    "admin": principal("admin", OPERATOR_ROLES),
    "norole": principal("norole", frozenset()),
}


class FakeAuthenticator:
    async def verify(self, token: str) -> Principal:
        try:
            return PRINCIPALS[token]
        except KeyError:
            raise unauthorized() from None


@dataclass
class FakePublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError
        self.published.append((subject, json.loads(payload), message_id))


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})
    operations: dict[str, OperationRecord] = field(default_factory=lambda: {})
    calls: int = 0

    async def get_user(self, resource_id: str) -> ResourceRecord | None:
        self.calls += 1
        return self.resources.get(resource_id)

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        self.calls += 1
        return self.operations.get(operation_id)


def user_record(resource_id: str) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=2,
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "platformAccess": "granted",
            "givenName": "Ana",
            "familyName": "Souza",
            "email": "ana@example.com",
        },
        presence=None,
        observed=None,
        observed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def operation(operation_id: str, requested_by: str, *, digest: str = "d" * 64) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        resource_id="ana",
        operation_type="create",
        desired_generation=1,
        request_digest=digest,
        operation_status="accepted",
        operation_status_reason=None,
        requested_by=requested_by,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )


@dataclass
class Harness:
    client: httpx.AsyncClient
    publisher: FakePublisher
    repository: FakeRepository
    clock: list[float]


@pytest.fixture
def harness() -> Harness:
    counter = itertools.count(1)
    publisher, repository = FakePublisher(), FakeRepository()
    clock = [0.0]
    deps = Dependencies(
        settings=ApiSettings(anonymous_rate_limit=3, anonymous_rate_window_seconds=60),
        authenticator=FakeAuthenticator(),
        repository=repository,
        publisher=publisher,
        limiter=SlidingWindowLimiter(3, 60, monotonic=lambda: clock[0]),
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, publisher, repository, clock)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


# ---------------------------------------------------------------------- autenticação e autorização


async def test_health_probes_are_public_and_readiness_reflects_the_dependencies(
    harness: Harness,
) -> None:
    for probe in ("live", "startup", "ready"):
        response = await harness.client.get(f"/health/{probe}")
        assert response.status_code == 200
        assert response.json()["status"] == "UP"


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer ruim"}, {"Authorization": "Basic x"}]
)
async def test_missing_or_invalid_token_is_401_with_the_error_contract(
    harness: Harness, headers: dict[str, str]
) -> None:
    response = await harness.client.get("/v1/users/ana", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_role_is_403(harness: Harness) -> None:
    harness.repository.resources["ana"] = user_record("ana")
    response = await harness.client.get("/v1/users/ana", headers=auth("norole"))
    assert response.status_code == 403
    assert harness.publisher.published == []


# ---------------------------------------------------------------------- cadastro anônimo


REGISTRATION = {"givenName": "Ana", "familyName": "Souza", "email": "ana@example.com"}


async def test_registration_is_anonymous_uniform_and_never_touches_the_ssot(
    harness: Harness,
) -> None:
    response = await harness.client.post("/v1/users", json=REGISTRATION)
    again = await harness.client.post("/v1/users", json=REGISTRATION)

    assert (response.status_code, again.status_code) == (202, 202)
    assert set(response.json()) == set(again.json()) == {"resourceId", "operationId"}
    assert harness.repository.calls == 0  # sem consulta: nada revela se o e-mail já existe
    subject, payload, _ = harness.publisher.published[0]
    assert subject.startswith("receiver.requested.core.user.") and subject.endswith(".create")
    assert payload["requestedBy"] == "anonymous"
    assert payload["data"]["specification"] == REGISTRATION


@pytest.mark.parametrize(
    "extra", [{"password": "Segredo!123"}, {"resourceId": "x"}, {"requestedBy": "admin"}]
)
async def test_registration_rejects_password_and_server_fields(
    harness: Harness, extra: dict[str, str]
) -> None:
    response = await harness.client.post("/v1/users", json={**REGISTRATION, **extra})
    assert response.status_code == 400
    assert "Segredo" not in response.text
    assert harness.publisher.published == []


async def test_registration_is_rate_limited_by_the_gateway_supplied_origin(
    harness: Harness,
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.2"}
    statuses = [
        (await harness.client.post("/v1/users", json=REGISTRATION, headers=headers)).status_code
        for _ in range(4)
    ]
    assert statuses == [202, 202, 202, 429]
    limited = await harness.client.post("/v1/users", json=REGISTRATION, headers=headers)
    assert limited.json()["errorCode"] == "RateLimited"
    assert int(limited.headers["retry-after"]) >= 1
    # outra origem não é afetada; o valor forjado à esquerda não muda a origem
    other = {"X-Forwarded-For": "198.51.100.1, 10.0.0.9"}
    assert (
        await harness.client.post("/v1/users", json=REGISTRATION, headers=other)
    ).status_code == 202
    forged = {"X-Forwarded-For": "1.2.3.4, 10.0.0.2"}
    assert (
        await harness.client.post("/v1/users", json=REGISTRATION, headers=forged)
    ).status_code == 429
    harness.clock[0] = 61.0
    assert (
        await harness.client.post("/v1/users", json=REGISTRATION, headers=headers)
    ).status_code == 202


# ---------------------------------------------------------------------- User


async def test_user_reads_and_deletes_only_itself(harness: Harness) -> None:
    harness.repository.resources["ana"] = user_record("ana")
    own = await harness.client.get("/v1/users/ana", headers=auth("ana"))
    assert own.status_code == 200
    assert generated.User.model_validate(own.json()).desired.email is not None
    assert (await harness.client.get("/v1/users/ana", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get("/v1/users/ana", headers=auth("admin"))).status_code == 200

    assert (
        await harness.client.delete("/v1/users/ana?resourceVersion=2", headers=auth("bia"))
    ).status_code == 404
    deleted = await harness.client.delete("/v1/users/ana?resourceVersion=2", headers=auth("ana"))
    assert deleted.status_code == 202
    assert harness.publisher.published[0][0] == "receiver.requested.core.user.ana.delete"


# ---------------------------------------------------------------------- Operation


async def test_operation_is_readable_only_by_the_requester_and_operators(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "ana")
    harness.repository.operations["op-anon"] = operation("op-anon", "anonymous")
    path = "/v1/users/ana/operations"

    own = await harness.client.get(f"{path}/op-1", headers=auth("ana"))
    assert own.status_code == 200
    generated.Operation.model_validate(own.json())
    assert "requestedBy" not in own.text
    assert (await harness.client.get(f"{path}/op-1", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-1", headers=auth("admin"))).status_code == 200
    # a Operation do cadastro (solicitante anônimo) só é legível por operadores
    assert (await harness.client.get(f"{path}/op-anon", headers=auth("ana"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-anon", headers=auth("admin"))).status_code == 200
    assert (await harness.client.get(f"{path}/ghost", headers=auth("ana"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-1")).status_code == 401


async def test_operation_of_another_resource_is_404(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "ana")
    response = await harness.client.get("/v1/users/outro/operations/op-1", headers=auth("ana"))
    assert response.status_code == 404
