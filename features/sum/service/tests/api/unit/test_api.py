"""API de `sum.service`: ligar e desligar serviços, posse do dono e pré-condições (decisão 0098)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from sum_service.api.domain.attachments import Attachment
from sum_service.api.domain.errors import unauthorized
from sum_service.api.domain.principal import Principal
from sum_service.api.domain.records import ResourceRecord
from sum_service.api.http.app import Dependencies, create_app
from sum_service.common.contracts import generated

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
CATALOG = {"ipm": ("ipm.organization.get", "ipm.organization.create")}
OWNER_PERMISSIONS = frozenset({"sum.ipm.enable", "sum.ipm.disable", "sum.ipm.get"})


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    "ana": principal("ana", OWNER_PERMISSIONS),
    "bia": principal("bia", OWNER_PERMISSIONS),
    "noperm": principal("noperm", frozenset()),
    "readonly": principal("readonly", frozenset({"sum.ipm.get"})),
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

    async def get_service(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def services_of(self, owner_account_id: str) -> list[ResourceRecord]:
        return sorted(
            (
                record
                for record in self.resources.values()
                if record.desired.get("ownerAccountId") == owner_account_id
            ),
            key=lambda record: record.resource_id,
        )


class FakeAttachments:
    def __init__(self) -> None:
        self.organizations: dict[str, int] = {}
        self.billing_accounts: set[str] = {"ana", "bia", "readonly"}
        self.synced = True

    @property
    def is_synced(self) -> bool:
        return self.synced

    def of(self, service: str, owner_account_id: str) -> list[Attachment]:
        count = self.organizations.get(owner_account_id, 0) if service == "ipm" else 0
        return [Attachment("Organization", "Organizations", count)] if count else []

    def has_billing_account(self, owner_account_id: str) -> bool:
        return owner_account_id in self.billing_accounts


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

    async def lock_pair(self, owner_account_id: str, service: str) -> dict[str, Any] | None:
        pair = [
            record
            for record in self._resources.values()
            if record.desired.get("ownerAccountId") == owner_account_id
            and record.desired.get("service") == service
        ]
        if not pair:
            return None
        record = sorted(pair, key=lambda item: item.lifecycle != "present")[0]
        return {
            "resource_id": record.resource_id,
            "resource_version": record.resource_version,
            "lifecycle": record.lifecycle,
            "desired": dict(record.desired),
        }

    async def insert_resource(
        self,
        resource_id: str,
        *,
        schema_version: str,
        desired: Any,
        requested_by: str,
        correlation_id: str,
    ) -> None:
        self._resources[resource_id] = link_record(resource_id, desired, version=1, phase="Pending")
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
        phase: str,
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None:
        record = self._resources[resource_id]
        if record.resource_version != expected_resource_version:
            return None
        generation = record.desired_generation + 1
        self._resources[resource_id] = replace(
            record,
            lifecycle=desired["lifecycle"],
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


def link_record(
    resource_id: str,
    desired: Any,
    *,
    version: int = 2,
    phase: str = "Ready",
    generation: int = 1,
) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=generation,
        observed_generation=generation if phase == "Ready" else None,
        lifecycle=desired["lifecycle"],
        reconciliation="active",
        phase=phase,
        conditions=[],
        desired=dict(desired),
        presence=None,
        observed=None,
        observed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def ipm_desired(owner: str, *, lifecycle: str = "present") -> dict[str, Any]:
    permissions = list(CATALOG["ipm"]) if lifecycle == "present" else []
    return {
        "lifecycle": lifecycle,
        "reconciliation": "active",
        "ownerAccountId": owner,
        "service": "ipm",
        "servicePermissions": permissions,
        "managedPermissions": sorted(CATALOG["ipm"]),
    }


def ipm_link(
    resource_id: str, owner: str = "ana", *, version: int = 2, lifecycle: str = "present"
) -> ResourceRecord:
    return link_record(resource_id, ipm_desired(owner, lifecycle=lifecycle), version=version)


@dataclass
class Harness:
    client: httpx.AsyncClient
    repository: FakeRepository
    store: FakeAdmissionStore
    attachments: FakeAttachments


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
    deps = Dependencies(
        authenticator=FakeAuthenticator(),
        repository=repository,
        admissions=store,
        attachments=attachments,
        catalog=CATALOG,
        clock=lambda: NOW,
        identifiers=next_id,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, repository, store, attachments)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


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
    response = await harness.client.get("/v1/sum/services", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_permission_is_403_and_writes_nothing(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=auth("noperm")
    )
    assert response.status_code == 403
    assert harness.store.outbox == []
    assert harness.repository.resources == {}


async def test_the_permission_is_the_one_of_the_service_not_of_another(harness: Harness) -> None:
    harness.attachments.billing_accounts.add("noperm")
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "bsm"}, headers=auth("ana")
    )
    assert response.status_code == 403  # `ana` só tem permissões do `ipm`


# ---------------------------------------------------------------------- ligar


async def test_enabling_a_service_admits_the_link_synchronously(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=auth("ana")
    )

    assert response.status_code == 201
    body = generated.ServiceResource.model_validate(response.json())
    record = harness.repository.resources[body.resource_id]
    assert record.desired["ownerAccountId"] == "ana"  # o dono é o `sub`, nunca o corpo
    assert record.desired["servicePermissions"] == list(CATALOG["ipm"])
    assert harness.store.requesters[body.resource_id] == "ana"
    ((subject, payload),) = harness.store.outbox
    assert subject == f"manager.desired.sum.service.{body.resource_id}.changed"
    assert payload["emitter"] == "api" and payload["requestedBy"] == "ana"
    assert payload["desiredGeneration"] == 1


async def test_the_client_cannot_choose_the_owner(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/sum/services",
        json={"service": "ipm", "ownerAccountId": "bia"},
        headers=auth("ana"),
    )
    assert response.status_code == 400
    assert harness.store.outbox == []


@pytest.mark.parametrize("service", ["IPM", "i", "ipm-x", "1ipm"])
async def test_an_invalid_service_name_is_400(harness: Harness, service: str) -> None:
    response = await harness.client.post(
        "/v1/sum/services", json={"service": service}, headers=auth("ana")
    )
    assert response.status_code == 400


async def test_a_service_outside_the_catalog_is_409(harness: Harness) -> None:
    PRINCIPALS["ana"] = principal("ana", OWNER_PERMISSIONS | {"sum.zzz.enable"})
    try:
        response = await harness.client.post(
            "/v1/sum/services", json={"service": "zzz"}, headers=auth("ana")
        )
    finally:
        PRINCIPALS["ana"] = principal("ana", OWNER_PERMISSIONS)
    assert response.status_code == 409
    assert response.json()["errorCode"] == "ServiceNotAvailable"
    assert harness.store.outbox == []


async def test_enabling_requires_a_billing_account(harness: Harness) -> None:
    harness.attachments.billing_accounts.discard("ana")
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "BillingAccountRequired"
    assert harness.store.outbox == []


async def test_enabling_does_not_proceed_while_the_projections_are_syncing(
    harness: Harness,
) -> None:
    harness.attachments.synced = False
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=auth("ana")
    )
    assert response.status_code == 503
    assert response.json()["errorCode"] == "ProjectionSyncPending"
    assert response.headers["Retry-After"] == "2"
    assert harness.store.outbox == []


async def test_enabling_an_enabled_service_is_409(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1")
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "AlreadyEnabled"
    assert harness.store.outbox == []


async def test_enabling_again_reuses_the_link_with_a_new_generation(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", lifecycle="absent")
    response = await harness.client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=auth("ana")
    )

    assert response.status_code == 201
    assert response.json()["resourceId"] == "link-1"
    assert len(harness.repository.resources) == 1
    record = harness.repository.resources["link-1"]
    assert (record.lifecycle, record.desired_generation) == ("present", 2)
    ((_, payload),) = harness.store.outbox
    assert payload["desiredGeneration"] == 2


async def test_the_same_idempotency_key_returns_the_same_link_without_writing_again(
    harness: Harness,
) -> None:
    headers = {**auth("ana"), "Idempotency-Key": "chave-1"}
    first = await harness.client.post("/v1/sum/services", json={"service": "ipm"}, headers=headers)
    again = await harness.client.post("/v1/sum/services", json={"service": "ipm"}, headers=headers)

    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json()["resourceId"] == again.json()["resourceId"]
    assert len(harness.store.outbox) == 1


async def test_reusing_the_idempotency_key_with_other_content_is_422(harness: Harness) -> None:
    PRINCIPALS["ana"] = principal("ana", OWNER_PERMISSIONS | {"sum.bsm.enable"})
    try:
        headers = {**auth("ana"), "Idempotency-Key": "chave-2"}
        await harness.client.post("/v1/sum/services", json={"service": "ipm"}, headers=headers)
        other = await harness.client.post(
            "/v1/sum/services", json={"service": "bsm"}, headers=headers
        )
    finally:
        PRINCIPALS["ana"] = principal("ana", OWNER_PERMISSIONS)
    assert other.status_code == 422
    assert other.json()["errorCode"] == "IdempotencyKeyReused"
    assert len(harness.store.outbox) == 1


async def test_invalid_idempotency_key_is_400(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/sum/services",
        json={"service": "ipm"},
        headers={**auth("ana"), "Idempotency-Key": "chave invalida!"},
    )
    assert response.status_code == 400
    assert harness.store.outbox == []


# ---------------------------------------------------------------------- leitura


async def test_a_link_is_read_only_by_its_owner(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", "ana")

    own = await harness.client.get("/v1/sum/services/link-1", headers=auth("ana"))
    other = await harness.client.get("/v1/sum/services/link-1", headers=auth("bia"))
    missing = await harness.client.get("/v1/sum/services/nao-existe", headers=auth("ana"))

    assert own.status_code == 200
    generated.ServiceResource.model_validate(own.json())
    assert other.status_code == 404  # não revela que a ligação existe
    assert missing.status_code == 404


async def test_reading_needs_the_get_permission_of_the_service(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", "noperm")
    response = await harness.client.get("/v1/sum/services/link-1", headers=auth("noperm"))
    assert response.status_code == 403


async def test_the_list_has_only_the_links_of_the_requester(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", "ana")
    harness.repository.resources["link-2"] = ipm_link("link-2", "bia")

    response = await harness.client.get("/v1/sum/services", headers=auth("ana"))

    assert response.status_code == 200
    items = generated.ServiceListResponse.model_validate(response.json()).items
    assert [item.resource_id for item in items] == ["link-1"]


async def test_the_list_hides_the_links_of_services_without_the_get_permission(
    harness: Harness,
) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", "noperm")
    response = await harness.client.get("/v1/sum/services", headers=auth("noperm"))
    assert response.status_code == 200
    assert response.json() == {"items": []}


# ---------------------------------------------------------------------- desligar


async def test_disabling_marks_the_link_absent_and_keeps_the_row(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1")

    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("ana")
    )

    assert response.status_code == 202
    assert response.json()["desired"]["lifecycle"] == "absent"
    record = harness.repository.resources["link-1"]  # a linha não é apagada (decisão 0033)
    assert (record.lifecycle, record.desired["servicePermissions"]) == ("absent", [])
    ((subject, payload),) = harness.store.outbox
    assert subject == "manager.desired.sum.service.link-1.changed"
    assert payload["data"]["lifecycle"] == "absent"
    assert payload["desiredGeneration"] == 2


async def test_only_the_owner_disables_the_link(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", "ana")
    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("bia")
    )
    assert response.status_code == 404
    assert harness.store.outbox == []


async def test_disabling_needs_the_disable_permission(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", "readonly")
    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("readonly")
    )
    assert response.status_code == 403
    assert harness.store.outbox == []


async def test_disabling_is_refused_while_resources_are_attached(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1")
    harness.attachments.organizations["ana"] = 2

    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("ana")
    )

    assert response.status_code == 409
    assert response.json()["errorCode"] == "ResourcesAttached"
    assert "2 Organizations" in response.json()["message"]
    assert harness.repository.resources["link-1"].lifecycle == "present"
    assert harness.store.outbox == []


async def test_disabling_does_not_proceed_while_the_projections_are_syncing(
    harness: Harness,
) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1")
    harness.attachments.synced = False
    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("ana")
    )
    assert response.status_code == 503
    assert response.json()["errorCode"] == "ProjectionSyncPending"
    assert harness.store.outbox == []


async def test_disabling_with_a_stale_version_is_409(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", version=3)
    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "Conflict"
    assert harness.store.outbox == []


async def test_disabling_requires_the_resource_version(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1")
    response = await harness.client.delete("/v1/sum/services/link-1", headers=auth("ana"))
    assert response.status_code == 400


async def test_repeating_the_disable_of_a_disabled_link_changes_nothing(harness: Harness) -> None:
    harness.repository.resources["link-1"] = ipm_link("link-1", lifecycle="absent")
    harness.attachments.organizations["ana"] = 2  # nem a pré-condição é reavaliada

    response = await harness.client.delete(
        "/v1/sum/services/link-1", params={"resourceVersion": "2"}, headers=auth("ana")
    )

    assert response.status_code == 202
    assert harness.store.outbox == []
    assert harness.repository.resources["link-1"].desired_generation == 1
