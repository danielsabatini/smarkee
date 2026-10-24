"""API do Receiver do usuário da Organization: escopo, `bind`, catálogo, cota e contratos."""

import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ipm_user.common.contracts import generated
from ipm_user.common.ports import PublishError
from ipm_user.receiver.domain.access import AccessCheckError, OrganizationAccess
from ipm_user.receiver.domain.errors import unauthorized
from ipm_user.receiver.domain.principal import Principal
from ipm_user.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_user.receiver.domain.requests import operation_id_for, request_digest
from ipm_user.receiver.http.app import Dependencies, create_app
from ipm_user.receiver.settings import ApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ORG = "org-1"
OTHER_ORG = "org-2"
USER_PERMISSIONS = frozenset(
    {"ipm.user.create", "ipm.user.get", "ipm.user.list", "ipm.user.update", "ipm.user.delete"}
)
ROOT_PERMISSIONS = USER_PERMISSIONS | {"ipm.user.bind", "ipm.organization.get"}


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    # Dono da `org-1` (confirmado pelo Receiver da Organization).
    "root": principal("root", ROOT_PERMISSIONS),
    # Usuários da `org-1` (registro próprio no SSOT): sem e com `bind`.
    "bia": principal("bia", USER_PERMISSIONS),
    "binder": principal("binder", USER_PERMISSIONS | {"ipm.user.bind"}),
    # Usuária da `org-2`.
    "eve": principal("eve", USER_PERMISSIONS | {"ipm.user.bind"}),
    "admin": principal("admin", USER_PERMISSIONS | {"ipm.user.admin"}),
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
            raise PublishError("unavailable")
        self.published.append((subject, json.loads(payload), message_id))


def user(
    resource_id: str,
    organization_id: str = ORG,
    *,
    permissions: list[str] | None = None,
    version: int = 3,
    lifecycle: str = "present",
    protected: bool | None = False,
) -> ResourceRecord:
    """`protected=None` simula o registro sem o campo (vale desprotegido, decisão 0077)."""
    desired: dict[str, Any] = {
        "lifecycle": lifecycle,
        "organizationId": organization_id,
        "permissions": permissions if permissions is not None else ["ipm.user.get"],
    }
    if lifecycle == "present":
        desired |= {"givenName": "Bia", "familyName": "Lima", "email": f"{resource_id}@x.com"}
    if protected is not None:
        desired["deletionProtection"] = protected
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=desired,
        presence="present",
        observed={
            "permissions": desired["permissions"],
            "userState": "active",
            "emailVerified": True,
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})
    operations: dict[str, OperationRecord] = field(default_factory=lambda: {})

    async def get_user(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def list_users(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        items = [r for r in items if r.desired.get("organizationId") == organization_id]
        return [r for r in items if after is None or r.resource_id > after][:limit]

    async def count_users_in(self, organization_id: str) -> int:
        return sum(
            1 for r in self.resources.values() if r.desired.get("organizationId") == organization_id
        )

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        return self.operations.get(operation_id)


@dataclass
class FakeOrganizations:
    """Receiver da Organization: o dono de cada uma, pelo token."""

    owners: dict[str, str] = field(default_factory=lambda: {ORG: "token-root"})
    error: AccessCheckError | None = None
    calls: list[str] = field(default_factory=lambda: [])

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess:
        self.calls.append(organization_id)
        if self.error is not None:
            raise self.error
        if self.owners.get(organization_id) == access_token:
            return OrganizationAccess.OWNED
        return OrganizationAccess.NOT_OWNED


def operation(operation_id: str, requested_by: str, *, digest: str = "d" * 64) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        resource_id="u-1",
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
    organizations: FakeOrganizations


def dependencies(
    repository: FakeRepository,
    organizations: FakeOrganizations,
    publisher: FakePublisher,
    **overrides: Any,
) -> Dependencies:
    counter = itertools.count(1)
    return Dependencies(
        settings=ApiSettings(user_quota=3),
        authenticator=FakeAuthenticator(),
        repository=repository,
        organizations=organizations,
        publisher=publisher,
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
        **overrides,
    )


@pytest.fixture
def harness() -> Harness:
    publisher, repository, organizations = FakePublisher(), FakeRepository(), FakeOrganizations()
    repository.resources |= {
        "bia": user("bia", permissions=sorted(USER_PERMISSIONS)),
        "binder": user("binder"),
        "eve": user("eve", OTHER_ORG),
    }
    deps = dependencies(repository, organizations, publisher)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, publisher, repository, organizations)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


def body(**fields: Any) -> dict[str, Any]:
    return {
        "organizationId": ORG,
        "givenName": "Caio",
        "familyName": "Reis",
        "email": "Caio.Reis@Example.com",
        **fields,
    }


async def create(harness: Harness, subject: str, **fields: Any) -> httpx.Response:
    return await harness.client.post("/v1/ipm/users", json=body(**fields), headers=auth(subject))


# ---------------------------------------------------------------------- autenticação e saúde


async def test_health_probes_are_public(harness: Harness) -> None:
    for probe in ("live", "startup", "ready"):
        response = await harness.client.get(f"/health/{probe}")
        assert (response.status_code, response.json()["status"]) == (200, "UP")


async def test_readiness_is_down_when_a_critical_dependency_is_down() -> None:
    deps = dependencies(
        FakeRepository(), FakeOrganizations(), FakePublisher(), is_ready=lambda: False
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    ready = await client.get("/health/ready")
    assert ready.status_code == 503 and ready.json()["status"] == "DOWN"
    assert (await client.get("/health/live")).status_code == 200


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer ruim"}, {"Authorization": "Basic x"}]
)
async def test_missing_or_invalid_token_is_401_with_the_error_contract(
    harness: Harness, headers: dict[str, str]
) -> None:
    response = await harness.client.get(f"/v1/ipm/users?organizationId={ORG}", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())


async def test_missing_permission_is_403(harness: Harness) -> None:
    response = await create(harness, "norole")
    assert response.status_code == 403
    assert harness.publisher.published == []


# ---------------------------------------------------------------------- criar


async def test_root_creates_a_user_and_the_requested_carries_the_quota(harness: Harness) -> None:
    response = await create(harness, "root", permissions=["ipm.user.list", "ipm.user.get"])

    assert response.status_code == 202
    accepted = generated.ApiAcceptedResponse.model_validate(response.json())
    ((subject, payload, _),) = harness.publisher.published
    assert subject == f"receiver.requested.ipm.user.{accepted.resource_id}.create"
    data = generated.MessageEnvelope.model_validate(payload).data
    specification = {
        "organizationId": ORG,
        "givenName": "Caio",
        "familyName": "Reis",
        "email": "caio.reis@example.com",  # normalizado: é o nome de login
        "permissions": ["ipm.user.get", "ipm.user.list"],
        "deletionProtection": False,  # nasce desprotegido (decisão 0077)
    }
    assert data["specification"] == specification
    assert data["organizationQuotaLimit"] == 3
    assert data["requestDigest"] == request_digest(
        {"operation": "create", "specification": specification}
    )
    generated.UserRequestedCreateData.model_validate(data)
    assert harness.organizations.calls == [ORG]


async def test_a_user_of_the_organization_creates_without_asking_the_organization(
    harness: Harness,
) -> None:
    response = await create(harness, "bia", permissions=["ipm.user.get"])
    assert response.status_code == 202
    assert harness.organizations.calls == []  # reconhecida pelo próprio registro


async def test_operator_creates_without_quota_and_without_asking_the_organization(
    harness: Harness,
) -> None:
    response = await create(harness, "admin", organizationId="org-9")
    assert response.status_code == 202
    assert "organizationQuotaLimit" not in harness.publisher.published[0][1]["data"]
    assert harness.organizations.calls == []


@pytest.mark.parametrize("subject", ["eve", "root"])
async def test_nobody_creates_in_an_organization_where_they_do_not_act(
    harness: Harness, subject: str
) -> None:
    response = await create(harness, subject, organizationId="org-9")
    assert response.status_code == 404
    assert harness.publisher.published == []


async def test_a_user_being_removed_no_longer_acts_in_the_organization(harness: Harness) -> None:
    harness.repository.resources["bia"] = user("bia", lifecycle="absent")
    assert (await create(harness, "bia")).status_code == 404


async def test_organization_check_failures_are_explicit(harness: Harness) -> None:
    harness.organizations.error = AccessCheckError(retryable=True)
    unavailable = await create(harness, "root")
    assert (unavailable.status_code, unavailable.headers["retry-after"]) == (503, "5")
    harness.organizations.error = AccessCheckError(retryable=False)
    assert (await create(harness, "root")).status_code == 403
    assert harness.publisher.published == []


async def test_permissions_outside_the_grant_catalog_are_400(harness: Harness) -> None:
    response = await create(harness, "root", permissions=["ipm.organization.delete"])
    assert (response.status_code, response.json()["field"]) == (400, "permissions")
    assert "ipm.organization.delete" in response.json()["message"]
    assert harness.publisher.published == []


async def test_without_bind_only_permissions_the_requester_has_can_be_given(
    harness: Harness,
) -> None:
    refused = await create(harness, "bia", permissions=["ipm.user.bind"])
    assert refused.status_code == 403
    assert (await create(harness, "bia", permissions=["ipm.user.get"])).status_code == 202
    assert (
        await create(harness, "binder", permissions=["ipm.organization.get"])
    ).status_code == 202
    assert (await create(harness, "root", permissions=["ipm.user.bind"])).status_code == 202


async def test_quota_is_checked_before_publishing(harness: Harness) -> None:
    harness.repository.resources["u-9"] = user("u-9")  # bia, binder e u-9: 3 na org-1
    response = await create(harness, "root")
    assert (response.status_code, response.json()["errorCode"]) == (403, "QuotaExceeded")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("fields", "field_name"),
    [
        ({"email": "nao-e-email"}, "email"),
        ({"password": "segredo"}, "password"),
        ({"permissions": ["Nao Valida"]}, "permissions.0"),
        ({"organizationId": "Org Inválida"}, "organizationId"),
    ],
)
async def test_invalid_body_is_400_and_does_not_echo_values(
    harness: Harness, fields: dict[str, Any], field_name: str
) -> None:
    response = await create(harness, "root", **fields)
    assert response.status_code == 400
    assert response.json()["field"] == field_name
    for value in fields.values():
        assert str(value) not in response.text.replace("Campo inválido", "")


async def test_publish_failure_is_a_retryable_503(harness: Harness) -> None:
    harness.publisher.fail = True
    response = await create(harness, "root")
    assert (response.status_code, response.json()["errorCode"]) == (503, "ServiceUnavailable")


async def test_idempotency_key_derives_a_stable_operation_id_per_requester(
    harness: Harness,
) -> None:
    response = await harness.client.post(
        "/v1/ipm/users", json=body(), headers={**auth("root"), "Idempotency-Key": "k-1"}
    )
    assert response.json()["operationId"] == operation_id_for(
        module="ipm", resource_type="user", requested_by="root", idempotency_key="k-1"
    )


async def test_same_key_with_other_content_is_422(harness: Harness) -> None:
    operation_id = operation_id_for(
        module="ipm", resource_type="user", requested_by="root", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "root", digest="f" * 64)
    response = await harness.client.post(
        "/v1/ipm/users", json=body(), headers={**auth("root"), "Idempotency-Key": "k-1"}
    )
    assert (response.status_code, response.json()["errorCode"]) == (422, "IdempotencyKeyReused")


# ---------------------------------------------------------------------- ler e listar


async def test_get_is_scoped_to_the_organization(harness: Harness) -> None:
    ok = await harness.client.get("/v1/ipm/users/binder", headers=auth("bia"))
    assert ok.status_code == 200
    view = generated.User.model_validate(ok.json())
    assert (view.desired.organization_id, view.desired.deletion_protection) == (ORG, False)
    assert "requestedBy" not in ok.text and "failureCount" not in ok.text
    assert (
        await harness.client.get("/v1/ipm/users/binder", headers=auth("root"))
    ).status_code == 200
    assert (
        await harness.client.get("/v1/ipm/users/binder", headers=auth("eve"))
    ).status_code == 404
    assert (await harness.client.get("/v1/ipm/users/ghost", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get("/v1/ipm/users/eve", headers=auth("admin"))).status_code == 200


async def test_every_user_reads_their_own_record_without_a_permission(harness: Harness) -> None:
    PRINCIPALS["self"] = principal("self", frozenset())
    harness.repository.resources["self"] = user("self")
    try:
        response = await harness.client.get("/v1/ipm/users/self", headers=auth("self"))
        assert response.status_code == 200
        other = await harness.client.get("/v1/ipm/users/bia", headers=auth("self"))
        assert other.status_code == 403
    finally:
        del PRINCIPALS["self"]


async def test_list_is_scoped_to_one_organization_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[f"a-{index}"] = user(f"a-{index}")
    first = await harness.client.get(
        f"/v1/ipm/users?organizationId={ORG}&limit=2", headers=auth("bia")
    )
    page = generated.UserList.model_validate(first.json())
    assert [item.resource_id for item in page.items] == ["a-0", "a-1"]
    assert page.next_cursor == "a-1"
    rest = await harness.client.get(
        f"/v1/ipm/users?organizationId={ORG}&cursor=a-1", headers=auth("bia")
    )
    assert [item["resourceId"] for item in rest.json()["items"]] == ["a-2", "bia", "binder"]
    other = await harness.client.get(f"/v1/ipm/users?organizationId={ORG}", headers=auth("eve"))
    assert other.status_code == 404
    missing = await harness.client.get("/v1/ipm/users", headers=auth("bia"))
    assert (missing.status_code, missing.json()["field"]) == (400, "organizationId")


# ---------------------------------------------------------------------- alterar e remover


async def test_update_publishes_permissions_and_protection_with_the_version(
    harness: Harness,
) -> None:
    response = await harness.client.patch(
        "/v1/ipm/users/binder",
        json={
            "resourceVersion": "3",
            "permissions": ["ipm.user.list"],
            "deletionProtection": True,
        },
        headers=auth("root"),
    )
    assert response.status_code == 202
    data = harness.publisher.published[0][1]["data"]
    assert data["specification"] == {"permissions": ["ipm.user.list"], "deletionProtection": True}
    generated.UserRequestedUpdateData.model_validate(data)


async def test_without_bind_permissions_the_requester_lacks_cannot_be_given_or_taken(
    harness: Harness,
) -> None:
    harness.repository.resources["x"] = user("x", permissions=["ipm.organization.get"])
    path = "/v1/ipm/users/x"
    taken = await harness.client.patch(
        path, json={"resourceVersion": "3", "permissions": []}, headers=auth("bia")
    )
    given = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "permissions": ["ipm.organization.get", "ipm.user.bind"]},
        headers=auth("bia"),
    )
    assert (taken.status_code, given.status_code) == (403, 403)
    allowed = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "permissions": ["ipm.organization.get", "ipm.user.get"]},
        headers=auth("bia"),
    )
    assert allowed.status_code == 202


@pytest.mark.parametrize(
    ("payload", "subject", "status"),
    [
        ({"resourceVersion": "2", "deletionProtection": True}, "root", 409),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, "root", 403),
        ({"resourceVersion": "3"}, "root", 400),
        ({"resourceVersion": "3", "permissions": ["x.y.z"]}, "root", 400),
        ({"resourceVersion": "3", "deletionProtection": True}, "eve", 404),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, "admin", 202),
    ],
)
async def test_update_rules(
    harness: Harness, payload: dict[str, Any], subject: str, status: int
) -> None:
    response = await harness.client.patch(
        "/v1/ipm/users/binder", json=payload, headers=auth(subject)
    )
    assert response.status_code == status


async def test_delete_requires_the_version_and_the_organization(harness: Harness) -> None:
    path = "/v1/ipm/users/binder"
    assert (await harness.client.delete(path, headers=auth("root"))).status_code == 400
    stale = await harness.client.delete(f"{path}?resourceVersion=2", headers=auth("root"))
    assert stale.status_code == 409
    other = await harness.client.delete(f"{path}?resourceVersion=3", headers=auth("eve"))
    assert other.status_code == 404
    deleted = await harness.client.delete(f"{path}?resourceVersion=3", headers=auth("bia"))
    assert deleted.status_code == 202
    data = harness.publisher.published[0][1]["data"]
    generated.UserRequestedDeleteData.model_validate(data)


@pytest.mark.parametrize(("protected", "status"), [(True, 409), (False, 202), (None, 202)])
async def test_delete_is_refused_only_while_protected(
    harness: Harness, protected: bool | None, status: int
) -> None:
    harness.repository.resources["x"] = user("x", protected=protected)
    response = await harness.client.delete(
        "/v1/ipm/users/x?resourceVersion=3", headers=auth("root")
    )
    assert response.status_code == status
    if status == 409:
        assert response.json()["errorCode"] == "DeletionProtected"


# ---------------------------------------------------------------------- Operation


async def test_operation_is_readable_only_by_the_requester_and_operators(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "root")
    path = "/v1/ipm/users/u-1/operations"
    own = await harness.client.get(f"{path}/op-1", headers=auth("root"))
    assert own.status_code == 200
    generated.Operation.model_validate(own.json())
    assert (await harness.client.get(f"{path}/op-1", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-1", headers=auth("admin"))).status_code == 200
    other = await harness.client.get("/v1/ipm/users/u-2/operations/op-1", headers=auth("root"))
    assert other.status_code == 404
