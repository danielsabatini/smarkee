"""API de Account: cadastro anônimo, acesso do dono, admissão síncrona e exclusão segura."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from core_account.api.domain.account import UniqueValue
from core_account.api.domain.attachments import Attachment
from core_account.api.domain.errors import unauthorized
from core_account.api.domain.principal import Principal
from core_account.api.domain.ratelimit import SlidingWindowLimiter
from core_account.api.domain.records import ResourceRecord
from core_account.api.http.app import Dependencies, create_app
from core_account.api.settings import AccountApiSettings
from core_account.common.contracts import generated

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
OWNER_PERMISSIONS = frozenset({"core.account.get", "core.account.delete"})


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    "ana": principal("ana", OWNER_PERMISSIONS),
    "bia": principal("bia", OWNER_PERMISSIONS),
    "admin": principal("admin", OWNER_PERMISSIONS | {"core.account.admin"}),
    "noperm": principal("noperm", frozenset()),
}


class FakeAuthenticator:
    async def verify(self, token: str) -> Principal:
        try:
            return PRINCIPALS[token]
        except KeyError:
            raise unauthorized() from None


class FakeRepository:
    def __init__(self) -> None:
        self.resources: dict[str, ResourceRecord] = {}

    async def get_account(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)


class FakeAttachments:
    def __init__(self) -> None:
        self.attached: dict[str, list[Attachment]] = {}

    def of(self, account_id: str) -> list[Attachment]:
        return self.attached.get(account_id, [])


class FakeAdmissionTransaction:
    """Transação em memória (decisão 0098): grava como o SSOT, sem rede."""

    def __init__(self, store: FakeAdmissionStore) -> None:
        self._store = store

    @property
    def _resources(self) -> dict[str, ResourceRecord]:
        return self._store.repository.resources

    async def lock_idempotency(self, requested_by: str, key: str) -> None:
        return

    async def find_idempotency(self, requested_by: str, key: str) -> tuple[str, str] | None:
        return self._store.idempotency.get((requested_by, key))

    async def record_idempotency(
        self, requested_by: str, key: str, *, request_digest: str, resource_id: str
    ) -> None:
        self._store.idempotency[(requested_by, key)] = (request_digest, resource_id)

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool:
        return any(
            record.desired.get(unique.field) == unique.value
            for record in self._resources.values()
            if record.resource_id != excluding_resource_id and record.lifecycle == "present"
        )

    async def insert_resource(
        self,
        resource_id: str,
        *,
        schema_version: str,
        desired: Any,
        requested_by: str,
        correlation_id: str,
    ) -> None:
        self._resources[resource_id] = ResourceRecord(
            resource_id=resource_id,
            resource_version=1,
            desired_generation=1,
            observed_generation=None,
            lifecycle=desired["lifecycle"],
            reconciliation="active",
            phase="Pending",
            conditions=[],
            desired=dict(desired),
            presence=None,
            observed=None,
            observed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        self._store.requesters[resource_id] = requested_by

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        record = self._resources.get(resource_id)
        if record is None:
            return None
        return {
            "resource_version": record.resource_version,
            "desired_generation": record.desired_generation,
            "observed_generation": record.observed_generation,
            "lifecycle": record.lifecycle,
            "reconciliation": record.reconciliation,
            "desired": dict(record.desired),
            "phase": record.phase,
        }

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Any,
        reconciliation: str,
        phase: str,
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None:
        record = self._resources[resource_id]
        if record.resource_version != expected_resource_version:
            return None
        generation = record.desired_generation + (1 if dict(desired) != record.desired else 0)
        self._resources[resource_id] = replace(
            record,
            lifecycle=desired["lifecycle"],
            reconciliation=reconciliation,
            desired=dict(desired),
            desired_generation=generation,
            phase=phase,
            resource_version=record.resource_version + 1,
        )
        return generation

    async def add_to_outbox(self, message: Any, *, resource_id: str, subject: str) -> None:
        self._store.outbox.append((subject, dict(message)))

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None:
        return self._resources.get(resource_id)


class FakeAdmissionStore:
    """Aplica tudo ou nada: uma falha dentro da transação desfaz o que ela gravou."""

    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self.outbox: list[tuple[str, dict[str, Any]]] = []
        self.requesters: dict[str, str] = {}

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[FakeAdmissionTransaction]:
        snapshot = (
            dict(self.repository.resources),
            dict(self.idempotency),
            list(self.outbox),
            dict(self.requesters),
        )
        try:
            yield FakeAdmissionTransaction(self)
        except BaseException:
            self.repository.resources, self.idempotency, self.outbox, self.requesters = (
                snapshot[0],
                snapshot[1],
                snapshot[2],
                snapshot[3],
            )
            raise


def account_record(
    resource_id: str,
    *,
    email: str = "ana@example.com",
    version: int = 2,
    protected: bool | None = False,
    lifecycle: str = "present",
) -> ResourceRecord:
    desired: dict[str, Any] = {
        "lifecycle": lifecycle,
        "platformAccess": "granted",
        "platformPermissions": ["core.account.get"],
    }
    if lifecycle == "present":
        desired.update({"givenName": "Ana", "familyName": "Souza", "email": email})
    if protected is not None:
        desired["deletionProtection"] = protected
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        observed_generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        phase="Ready" if lifecycle == "present" else "Deleting",
        conditions=[],
        desired=desired,
        presence="present",
        observed=None,
        observed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class Harness:
    client: httpx.AsyncClient
    repository: FakeRepository
    store: FakeAdmissionStore
    attachments: FakeAttachments
    synced: list[bool] = field(default_factory=lambda: [True])
    clock: list[float] = field(default_factory=lambda: [0.0])


@pytest.fixture
def harness() -> Harness:
    seq = 0

    def next_id() -> str:
        nonlocal seq
        seq += 1
        return f"id-{seq:04d}"

    repository = FakeRepository()
    store = FakeAdmissionStore(repository)
    attachments = FakeAttachments()
    clock = [0.0]
    synced = [True]
    settings = AccountApiSettings()
    deps = Dependencies(
        settings=settings,
        authenticator=FakeAuthenticator(),
        repository=repository,
        admissions=store,
        attachments=attachments,
        limiter=SlidingWindowLimiter(3, 60, monotonic=lambda: clock[0]),
        are_attachments_synced=lambda: synced[0],
        identifiers=next_id,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, repository, store, attachments, synced, clock)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


REGISTRATION = {"givenName": "Ana", "familyName": "Souza", "email": "Ana@Example.com "}


# ---------------------------------------------------------------------- autenticação e autorização


async def test_health_probes_are_public(harness: Harness) -> None:
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
    response = await harness.client.get("/v1/core/accounts/ana", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_permission_is_403(harness: Harness) -> None:
    harness.repository.resources["noperm"] = account_record("noperm")
    response = await harness.client.get("/v1/core/accounts/noperm", headers=auth("noperm"))
    assert response.status_code == 403
    assert harness.store.outbox == []


# ---------------------------------------------------------------------- cadastro anônimo


async def test_registration_is_anonymous_and_admits_the_account_synchronously(
    harness: Harness,
) -> None:
    response = await harness.client.post("/v1/core/accounts", json=REGISTRATION)

    assert response.status_code == 202
    body = generated.AccountRegistrationResponse.model_validate(response.json())
    assert set(response.json()) == {"resourceId"}
    record = harness.repository.resources[body.resource_id]
    assert record.desired["email"] == "ana@example.com"  # normalizado
    assert record.desired["platformAccess"] == "granted"
    assert record.desired["deletionProtection"] is True
    assert harness.store.requesters[body.resource_id] == "anonymous"
    ((subject, payload),) = harness.store.outbox
    assert subject == f"manager.desired.core.account.{body.resource_id}.changed"
    assert payload["emitter"] == "api" and payload["requestedBy"] == "anonymous"


async def test_registration_with_a_used_email_answers_the_same_and_writes_nothing(
    harness: Harness,
) -> None:
    first = await harness.client.post("/v1/core/accounts", json=REGISTRATION)
    again = await harness.client.post("/v1/core/accounts", json=REGISTRATION)

    assert (first.status_code, again.status_code) == (202, 202)
    assert set(first.json()) == set(again.json()) == {"resourceId"}
    assert first.json()["resourceId"] != again.json()["resourceId"]
    assert list(harness.repository.resources) == [first.json()["resourceId"]]
    assert len(harness.store.outbox) == 1


@pytest.mark.parametrize(
    "extra", [{"password": "Segredo!123"}, {"resourceId": "x"}, {"requestedBy": "admin"}]
)
async def test_registration_rejects_password_and_server_fields(
    harness: Harness, extra: dict[str, str]
) -> None:
    response = await harness.client.post("/v1/core/accounts", json={**REGISTRATION, **extra})
    assert response.status_code == 400
    assert "Segredo" not in response.text
    assert harness.store.outbox == []


async def test_registration_is_rate_limited_by_the_gateway_supplied_origin(
    harness: Harness,
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.2"}

    async def register(extra: dict[str, str]) -> httpx.Response:
        email = f"u{len(harness.repository.resources)}@example.com"
        return await harness.client.post(
            "/v1/core/accounts", json={**REGISTRATION, "email": email}, headers=extra
        )

    statuses = [(await register(headers)).status_code for _ in range(4)]
    assert statuses == [202, 202, 202, 429]
    limited = await register(headers)
    assert limited.json()["errorCode"] == "RateLimited"
    assert int(limited.headers["retry-after"]) >= 1
    # outra origem não é afetada; o valor forjado à esquerda não muda a origem
    assert (await register({"X-Forwarded-For": "198.51.100.1, 10.0.0.9"})).status_code == 202
    assert (await register({"X-Forwarded-For": "1.2.3.4, 10.0.0.2"})).status_code == 429
    harness.clock[0] = 61.0
    assert (await register(headers)).status_code == 202


# ---------------------------------------------------------------------- leitura


async def test_account_is_read_only_by_itself_or_an_operator(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    own = await harness.client.get("/v1/core/accounts/ana", headers=auth("ana"))
    assert own.status_code == 200
    assert generated.Account.model_validate(own.json()).desired.email is not None
    other = await harness.client.get("/v1/core/accounts/ana", headers=auth("bia"))
    assert other.status_code == 404
    operator = await harness.client.get("/v1/core/accounts/ana", headers=auth("admin"))
    assert operator.status_code == 200
    missing = await harness.client.get("/v1/core/accounts/inexistente", headers=auth("admin"))
    assert missing.status_code == 404


async def test_view_defaults_to_protected_when_the_field_is_missing(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana", protected=None)
    response = await harness.client.get("/v1/core/accounts/ana", headers=auth("ana"))
    assert response.json()["desired"]["deletionProtection"] is True


# ---------------------------------------------------------------------- PATCH


async def test_account_may_change_its_own_deletion_protection(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana", protected=True)
    response = await harness.client.patch(
        "/v1/core/accounts/ana",
        json={"resourceVersion": "2", "deletionProtection": False},
        headers=auth("ana"),
    )
    assert response.status_code == 200
    view = generated.Account.model_validate(response.json())
    assert (view.resource_version, view.desired_generation, view.desired.deletion_protection) == (
        "3",
        2,
        False,
    )
    ((subject, payload),) = harness.store.outbox
    assert subject == "manager.desired.core.account.ana.changed"
    assert payload["desiredGeneration"] == 2 and payload["requestedBy"] == "ana"
    assert payload["data"]["deletionProtection"] is False


@pytest.mark.parametrize(
    ("caller", "body", "status"),
    [
        ("bia", {"resourceVersion": "2", "deletionProtection": False}, 404),
        ("ana", {"resourceVersion": "1", "deletionProtection": False}, 409),
        ("ana", {"resourceVersion": "2"}, 400),
        ("ana", {"resourceVersion": "2", "deletionProtection": False, "email": "x@y.com"}, 400),
    ],
)
async def test_protection_update_rules(
    harness: Harness, caller: str, body: dict[str, Any], status: int
) -> None:
    harness.repository.resources["ana"] = account_record("ana", protected=True)
    response = await harness.client.patch("/v1/core/accounts/ana", json=body, headers=auth(caller))
    assert response.status_code == status
    assert harness.store.outbox == []


async def test_invalid_idempotency_key_is_400(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana", protected=True)
    response = await harness.client.patch(
        "/v1/core/accounts/ana",
        json={"resourceVersion": "2", "deletionProtection": False},
        headers={**auth("ana"), "Idempotency-Key": "chave invalida!"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------- DELETE


async def test_delete_marks_the_account_absent_and_publishes_without_personal_data(
    harness: Harness,
) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=2", headers=auth("ana")
    )

    assert response.status_code == 202
    view = generated.Account.model_validate(response.json())
    assert (view.phase, view.desired.lifecycle.value) == ("Deleting", "absent")
    ((subject, payload),) = harness.store.outbox
    assert subject == "manager.desired.core.account.ana.changed"
    assert payload["data"]["lifecycle"] == "absent"
    assert "email" not in payload["data"]


async def test_only_the_owner_deletes_the_account(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    other = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=2", headers=auth("bia")
    )
    assert other.status_code == 404
    assert harness.store.outbox == []


@pytest.mark.parametrize("protected", [True, None])
async def test_delete_of_a_protected_account_is_refused(
    harness: Harness, protected: bool | None
) -> None:
    harness.repository.resources["ana"] = account_record("ana", protected=protected)
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=2", headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "DeletionProtected"
    assert harness.store.outbox == []


async def test_delete_is_refused_while_resources_are_attached(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    harness.attachments.attached["ana"] = [
        Attachment("Organization", "Organizations", 2),
        Attachment("Billing Account", "Billing Accounts", 1),
    ]
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=2", headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "ResourcesAttached"
    assert "2 Organizations" in response.json()["message"]
    assert "1 Billing Account" in response.json()["message"]
    assert harness.store.outbox == []


async def test_delete_does_not_proceed_while_the_projections_are_syncing(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    harness.synced[0] = False
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=2", headers=auth("ana")
    )
    assert response.status_code == 503
    assert response.json()["errorCode"] == "ProjectionSyncPending"
    assert response.headers["retry-after"] == "2"
    assert harness.store.outbox == []


async def test_an_operator_cannot_delete_another_account_until_it_can_be_verified(
    harness: Harness,
) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=2", headers=auth("admin")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "ResourcesNotVerifiable"
    assert harness.store.outbox == []


async def test_delete_with_a_stale_version_is_409(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record("ana")
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=1", headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "Conflict"


async def test_repeating_the_delete_of_an_account_already_being_removed_changes_nothing(
    harness: Harness,
) -> None:
    harness.repository.resources["ana"] = account_record(
        "ana", lifecycle="absent", version=3, protected=None
    )
    harness.attachments.attached["ana"] = [Attachment("Organization", "Organizations", 1)]
    harness.synced[0] = False
    response = await harness.client.delete(
        "/v1/core/accounts/ana?resourceVersion=3", headers=auth("ana")
    )
    assert response.status_code == 202
    assert harness.store.outbox == []  # nada a gravar nem a publicar


async def test_an_account_being_removed_does_not_accept_changes(harness: Harness) -> None:
    harness.repository.resources["ana"] = account_record(
        "ana", lifecycle="absent", version=3, protected=None
    )
    response = await harness.client.patch(
        "/v1/core/accounts/ana",
        json={"resourceVersion": "3", "deletionProtection": True},
        headers=auth("ana"),
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "NotPresent"
