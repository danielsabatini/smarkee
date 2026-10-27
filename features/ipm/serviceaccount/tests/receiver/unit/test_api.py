"""API do Receiver da service account: escopo, `bind`, catálogo, cota, chaves e contratos."""

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from ipm_serviceaccount.common.contracts import generated
from ipm_serviceaccount.common.ports import PublishError
from ipm_serviceaccount.receiver.domain.access import AccessCheckError, OrganizationAccess
from ipm_serviceaccount.receiver.domain.errors import unauthorized
from ipm_serviceaccount.receiver.domain.principal import Principal
from ipm_serviceaccount.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_serviceaccount.receiver.domain.requests import operation_id_for, request_digest
from ipm_serviceaccount.receiver.http.app import Dependencies, create_app
from ipm_serviceaccount.receiver.settings import ApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ORG = "org-1"
OTHER_ORG = "org-2"
VALID_UNTIL = NOW + timedelta(days=90)


def _pem(private: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> str:
    return (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def _fingerprint(pem: str) -> str:
    key = serialization.load_pem_public_key(pem.encode())
    der = key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()


KEY_A, KEY_B, KEY_C, KEY_D = (
    _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)) for _ in range(4)
)
KEY_SMALL = _pem(rsa.generate_private_key(public_exponent=65537, key_size=1024))  # noqa: S505
KEY_EC = _pem(ec.generate_private_key(ec.SECP256R1()))


def key_spec(pem: str, until: datetime = VALID_UNTIL) -> dict[str, str]:
    return {"publicKey": pem, "expiresAt": until.isoformat().replace("+00:00", "Z")}


def desired_key(pem: str, until: datetime = VALID_UNTIL) -> dict[str, str]:
    return {**key_spec(pem, until), "fingerprint": _fingerprint(pem)}


SA_PERMISSIONS = frozenset(
    {
        "ipm.serviceaccount.create",
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
        "ipm.serviceaccount.update",
        "ipm.serviceaccount.delete",
    }
)
ROOT_PERMISSIONS = SA_PERMISSIONS | {"ipm.serviceaccount.bind", "ipm.organization.get"}


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    # Dono da `org-1` (confirmado pelo Receiver da Organization).
    "root": principal("root", ROOT_PERMISSIONS),
    # Service accounts da `org-1` (registro próprio no SSOT): sem e com `bind`.
    "bia": principal("bia", SA_PERMISSIONS),
    "binder": principal("binder", SA_PERMISSIONS | {"ipm.serviceaccount.bind"}),
    # Service account da `org-2`.
    "eve": principal("eve", SA_PERMISSIONS | {"ipm.serviceaccount.bind"}),
    # Usuário humano da `org-1`, reconhecido pelo Receiver de User.
    "human": principal("human", SA_PERMISSIONS | {"ipm.serviceaccount.bind"}),
    "admin": principal("admin", SA_PERMISSIONS | {"ipm.serviceaccount.admin"}),
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


def serviceaccount(
    resource_id: str,
    organization_id: str = ORG,
    *,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
    version: int = 3,
    lifecycle: str = "present",
    protected: bool | None = False,
    keys: list[dict[str, str]] | None = None,
) -> ResourceRecord:
    """`protected=None` simula o registro sem o campo (vale protegido, decisão 0094)."""
    effective = (
        permissions
        if permissions is not None
        else ["ipm.serviceaccount.get", "ipm.serviceaccount.list"]
    )
    desired: dict[str, Any] = {
        "lifecycle": lifecycle,
        "organizationId": organization_id,
        "roles": roles if roles is not None else ["ipm.serviceaccountViewer"],
        "keys": keys if keys is not None else [desired_key(KEY_A)],
    }
    if lifecycle == "present":
        desired |= {"name": f"sa-{resource_id}"}
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
            "permissions": effective,
            "effectivePermissions": effective,
            "userState": "active",
            "accessTokenType": "jwt",
            "keys": [
                {"fingerprint": key["fingerprint"], "keyId": "k1", "status": "active"}
                for key in desired["keys"]
            ],
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})
    operations: dict[str, OperationRecord] = field(default_factory=lambda: {})

    async def get_serviceaccount(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def list_serviceaccounts(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        items = [r for r in items if r.desired.get("organizationId") == organization_id]
        return [r for r in items if after is None or r.resource_id > after][:limit]

    async def count_serviceaccounts_in(self, organization_id: str) -> int:
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


@dataclass
class FakeUsers:
    """Receiver de User: a Organização de cada usuário humano, pelo token."""

    members: dict[str, str] = field(default_factory=lambda: {"token-human": ORG})
    calls: list[str] = field(default_factory=lambda: [])

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None:
        self.calls.append(user_id)
        return self.members.get(access_token)


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
    users: FakeUsers


def dependencies(
    repository: FakeRepository,
    organizations: FakeOrganizations,
    publisher: FakePublisher,
    users: FakeUsers | None = None,
    **overrides: Any,
) -> Dependencies:
    counter = itertools.count(1)
    return Dependencies(
        settings=ApiSettings(serviceaccount_quota=3),
        authenticator=FakeAuthenticator(),
        repository=repository,
        organizations=organizations,
        users=users if users is not None else FakeUsers(),
        publisher=publisher,
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
        **overrides,
    )


@pytest.fixture
def harness() -> Harness:
    publisher, repository, organizations = FakePublisher(), FakeRepository(), FakeOrganizations()
    users = FakeUsers()
    repository.resources |= {
        "bia": serviceaccount("bia", permissions=sorted(SA_PERMISSIONS)),
        "binder": serviceaccount("binder"),
        "eve": serviceaccount("eve", OTHER_ORG),
    }
    deps = dependencies(repository, organizations, publisher, users)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, publisher, repository, organizations, users)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


def body(**fields: Any) -> dict[str, Any]:
    return {
        "organizationId": ORG,
        "name": "ci-deploy",
        "keys": [key_spec(KEY_B)],
        **fields,
    }


async def create(harness: Harness, subject: str, **fields: Any) -> httpx.Response:
    return await harness.client.post(
        "/v1/ipm/serviceaccounts", json=body(**fields), headers=auth(subject)
    )


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
    response = await harness.client.get(
        f"/v1/ipm/serviceaccounts?organizationId={ORG}", headers=headers
    )
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())


async def test_missing_permission_is_403(harness: Harness) -> None:
    response = await create(harness, "norole")
    assert response.status_code == 403
    assert harness.publisher.published == []


# ---------------------------------------------------------------------- criar


async def test_root_creates_a_serviceaccount_and_the_requested_carries_the_quota(
    harness: Harness,
) -> None:
    response = await create(harness, "root", roles=["ipm.serviceaccountViewer"])

    assert response.status_code == 202
    accepted = generated.ApiAcceptedResponse.model_validate(response.json())
    ((subject, payload, _),) = harness.publisher.published
    assert subject == f"receiver.requested.ipm.serviceaccount.{accepted.resource_id}.create"
    data = generated.MessageEnvelope.model_validate(payload).data
    specification = {
        "organizationId": ORG,
        "name": "ci-deploy",
        "roles": ["ipm.serviceaccountViewer"],
        "deletionProtection": True,  # nasce protegida (decisão 0094)
        "keys": [desired_key(KEY_B)],  # só a pública, com o fingerprint calculado aqui
    }
    assert data["specification"] == specification
    assert data["organizationQuotaLimit"] == 3
    assert data["requestDigest"] == request_digest(
        {"operation": "create", "specification": specification}
    )
    generated.ServiceAccountRequestedCreateData.model_validate(data)
    assert harness.organizations.calls == [ORG]


async def test_a_serviceaccount_of_the_organization_creates_without_asking_the_organization(
    harness: Harness,
) -> None:
    response = await create(harness, "bia")
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


async def test_a_serviceaccount_being_removed_no_longer_acts_in_the_organization(
    harness: Harness,
) -> None:
    harness.repository.resources["bia"] = serviceaccount("bia", lifecycle="absent")
    assert (await create(harness, "bia")).status_code == 404


async def test_organization_check_failures_are_explicit(harness: Harness) -> None:
    harness.organizations.error = AccessCheckError(retryable=True)
    unavailable = await create(harness, "root")
    assert (unavailable.status_code, unavailable.headers["retry-after"]) == (503, "5")
    harness.organizations.error = AccessCheckError(retryable=False)
    assert (await create(harness, "root")).status_code == 403
    assert harness.publisher.published == []


async def test_roles_outside_the_grant_catalog_are_400(harness: Harness) -> None:
    response = await create(harness, "root", roles=["bsm.accountAdmin"])
    assert (response.status_code, response.json()["field"]) == (400, "roles")
    assert "bsm.accountAdmin" in response.json()["message"]
    assert harness.publisher.published == []


async def test_without_bind_no_roles_can_be_given(
    harness: Harness,
) -> None:
    refused_bind = await create(harness, "bia", roles=["ipm.serviceaccountAdmin"])
    refused_own = await create(harness, "bia", roles=["ipm.serviceaccountViewer"])
    assert (refused_bind.status_code, refused_own.status_code) == (403, 403)
    assert (await create(harness, "bia", roles=[])).status_code == 202
    assert (await create(harness, "binder", roles=["ipm.organizationViewer"])).status_code == 202
    assert (await create(harness, "root", roles=["ipm.serviceaccountAdmin"])).status_code == 202


async def test_catalog_sync_pending_returns_503(harness: Harness) -> None:
    deps = dependencies(
        harness.repository,
        harness.organizations,
        harness.publisher,
        harness.users,
        is_catalog_synced=lambda: False,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    # Criar sem roles passa
    no_roles = await client.post(
        "/v1/ipm/serviceaccounts", json=body(roles=[]), headers=auth("root")
    )
    assert no_roles.status_code == 202

    # Criar com roles retorna 503 CatalogSyncPending e Retry-After: 2
    with_roles = await client.post(
        "/v1/ipm/serviceaccounts",
        json=body(roles=["ipm.serviceaccountViewer"]),
        headers=auth("root"),
    )
    assert with_roles.status_code == 503
    assert with_roles.json()["errorCode"] == "CatalogSyncPending"
    assert with_roles.headers.get("retry-after") == "2"

    # Patch alterando roles retorna 503 CatalogSyncPending
    patch_roles = await client.patch(
        "/v1/ipm/serviceaccounts/binder",
        json={"resourceVersion": "3", "roles": ["ipm.serviceaccountViewer"]},
        headers=auth("binder"),
    )
    assert patch_roles.status_code == 503
    assert patch_roles.json()["errorCode"] == "CatalogSyncPending"

    # Patch sem mexer em roles passa
    patch_clean = await client.patch(
        "/v1/ipm/serviceaccounts/binder",
        json={"resourceVersion": "3", "deletionProtection": True},
        headers=auth("binder"),
    )
    assert patch_clean.status_code == 202


async def test_quota_is_checked_before_publishing(harness: Harness) -> None:
    harness.repository.resources["u-9"] = serviceaccount("u-9")  # bia, binder e u-9: 3 na org-1
    response = await create(harness, "root")
    assert (response.status_code, response.json()["errorCode"]) == (403, "QuotaExceeded")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("fields", "field_name"),
    [
        ({"name": "Nome Inválido"}, "name"),
        ({"privateKey": "segredo"}, "privateKey"),
        ({"roles": ["Nao Valida"]}, "roles.0"),
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
        "/v1/ipm/serviceaccounts", json=body(), headers={**auth("root"), "Idempotency-Key": "k-1"}
    )
    assert response.json()["operationId"] == operation_id_for(
        module="ipm", resource_type="serviceaccount", requested_by="root", idempotency_key="k-1"
    )


async def test_same_key_with_other_content_is_422(harness: Harness) -> None:
    operation_id = operation_id_for(
        module="ipm", resource_type="serviceaccount", requested_by="root", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "root", digest="f" * 64)
    response = await harness.client.post(
        "/v1/ipm/serviceaccounts", json=body(), headers={**auth("root"), "Idempotency-Key": "k-1"}
    )
    assert (response.status_code, response.json()["errorCode"]) == (422, "IdempotencyKeyReused")


async def test_same_key_with_same_digest_returns_cached_operation_without_publishing(
    harness: Harness,
) -> None:
    first_resp = await harness.client.post(
        "/v1/ipm/serviceaccounts",
        json=body(),
        headers={**auth("root"), "Idempotency-Key": "k-stable"},
    )
    assert first_resp.status_code == 202
    op_id = first_resp.json()["operationId"]
    assert len(harness.publisher.published) == 1
    digest = harness.publisher.published[0][1]["data"]["requestDigest"]

    # Simula a persistência da operação no SSOT
    harness.repository.operations[op_id] = operation(op_id, "root", digest=digest)
    harness.publisher.published.clear()

    second_resp = await harness.client.post(
        "/v1/ipm/serviceaccounts",
        json=body(),
        headers={**auth("root"), "Idempotency-Key": "k-stable"},
    )
    assert second_resp.status_code == 202
    assert second_resp.json()["operationId"] == op_id
    assert len(harness.publisher.published) == 0


async def test_create_and_update_with_empty_description_is_rejected(harness: Harness) -> None:
    create_resp = await harness.client.post(
        "/v1/ipm/serviceaccounts",
        json={**body(), "description": ""},
        headers=auth("root"),
    )
    assert create_resp.status_code == 400
    assert create_resp.json()["field"] == "description"

    patch_resp = await harness.client.patch(
        "/v1/ipm/serviceaccounts/binder",
        json={"resourceVersion": "3", "description": ""},
        headers=auth("root"),
    )
    assert patch_resp.status_code == 400
    assert patch_resp.json()["field"] == "description"


async def test_patch_retained_key_ignores_new_expires_at(harness: Harness) -> None:
    original_expiry = NOW + timedelta(days=15)
    harness.repository.resources["retained-sa"] = serviceaccount(
        "retained-sa", keys=[desired_key(KEY_A, original_expiry)]
    )
    attempted_expiry = NOW + timedelta(days=60)
    response = await harness.client.patch(
        "/v1/ipm/serviceaccounts/retained-sa",
        json={"resourceVersion": "3", "keys": [key_spec(KEY_A, attempted_expiry)]},
        headers=auth("root"),
    )
    assert response.status_code == 202
    keys = harness.publisher.published[0][1]["data"]["specification"]["keys"]
    by_fingerprint = {key["fingerprint"]: key for key in keys}
    # O vencimento mantido DEVE ser o original retido, não o tentado
    expected_expiry = desired_key(KEY_A, original_expiry)["expiresAt"]
    assert by_fingerprint[_fingerprint(KEY_A)]["expiresAt"] == expected_expiry


# ---------------------------------------------------------------------- ler e listar


async def test_get_is_scoped_to_the_organization(harness: Harness) -> None:
    ok = await harness.client.get("/v1/ipm/serviceaccounts/binder", headers=auth("bia"))
    assert ok.status_code == 200
    view = generated.ServiceAccount.model_validate(ok.json())
    assert (view.desired.organization_id, view.desired.deletion_protection) == (ORG, False)
    assert view.observed is not None and view.observed.keys is not None
    assert view.observed.keys[0].status.value == "active"
    assert "requestedBy" not in ok.text and "failureCount" not in ok.text
    assert (
        await harness.client.get("/v1/ipm/serviceaccounts/binder", headers=auth("root"))
    ).status_code == 200
    assert (
        await harness.client.get("/v1/ipm/serviceaccounts/binder", headers=auth("eve"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/ipm/serviceaccounts/ghost", headers=auth("bia"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/ipm/serviceaccounts/eve", headers=auth("admin"))
    ).status_code == 200


async def test_every_serviceaccount_reads_their_own_record_without_a_permission(
    harness: Harness,
) -> None:
    PRINCIPALS["self"] = principal("self", frozenset())
    harness.repository.resources["self"] = serviceaccount("self")
    try:
        response = await harness.client.get("/v1/ipm/serviceaccounts/self", headers=auth("self"))
        assert response.status_code == 200
        other = await harness.client.get("/v1/ipm/serviceaccounts/bia", headers=auth("self"))
        assert other.status_code == 403
    finally:
        del PRINCIPALS["self"]


async def test_list_is_scoped_to_one_organization_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[f"a-{index}"] = serviceaccount(f"a-{index}")
    first = await harness.client.get(
        f"/v1/ipm/serviceaccounts?organizationId={ORG}&limit=2", headers=auth("bia")
    )
    page = generated.ServiceAccountList.model_validate(first.json())
    assert [item.resource_id for item in page.items] == ["a-0", "a-1"]
    assert page.next_cursor == "a-1"
    rest = await harness.client.get(
        f"/v1/ipm/serviceaccounts?organizationId={ORG}&cursor=a-1", headers=auth("bia")
    )
    assert [item["resourceId"] for item in rest.json()["items"]] == ["a-2", "bia", "binder"]
    other = await harness.client.get(
        f"/v1/ipm/serviceaccounts?organizationId={ORG}", headers=auth("eve")
    )
    assert other.status_code == 404
    missing = await harness.client.get("/v1/ipm/serviceaccounts", headers=auth("bia"))
    assert (missing.status_code, missing.json()["field"]) == (400, "organizationId")


# ---------------------------------------------------------------------- alterar e remover


async def test_update_publishes_roles_and_protection_with_the_version(
    harness: Harness,
) -> None:
    response = await harness.client.patch(
        "/v1/ipm/serviceaccounts/binder",
        json={
            "resourceVersion": "3",
            "roles": ["ipm.serviceaccountAdmin"],
            "deletionProtection": True,
        },
        headers=auth("root"),
    )
    assert response.status_code == 202
    data = harness.publisher.published[0][1]["data"]
    assert data["specification"] == {
        "roles": ["ipm.serviceaccountAdmin"],
        "deletionProtection": True,
    }
    generated.ServiceAccountRequestedUpdateData.model_validate(data)


async def test_without_bind_roles_cannot_be_given_or_taken(
    harness: Harness,
) -> None:
    harness.repository.resources["x"] = serviceaccount("x", roles=["ipm.organizationViewer"])
    path = "/v1/ipm/serviceaccounts/x"
    taken = await harness.client.patch(
        path, json={"resourceVersion": "3", "roles": []}, headers=auth("bia")
    )
    given_bind = await harness.client.patch(
        path,
        json={
            "resourceVersion": "3",
            "roles": ["ipm.organizationViewer", "ipm.serviceaccountAdmin"],
        },
        headers=auth("bia"),
    )
    given_own = await harness.client.patch(
        path,
        json={
            "resourceVersion": "3",
            "roles": ["ipm.organizationViewer", "ipm.serviceaccountViewer"],
        },
        headers=auth("bia"),
    )
    assert (taken.status_code, given_bind.status_code, given_own.status_code) == (403, 403, 403)
    unchanged = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "roles": ["ipm.organizationViewer"]},
        headers=auth("bia"),
    )
    assert unchanged.status_code == 202
    allowed_with_bind = await harness.client.patch(
        path,
        json={
            "resourceVersion": "3",
            "roles": ["ipm.organizationViewer", "ipm.serviceaccountViewer"],
        },
        headers=auth("binder"),
    )
    assert allowed_with_bind.status_code == 202


@pytest.mark.parametrize(
    ("payload", "subject", "status"),
    [
        ({"resourceVersion": "2", "deletionProtection": True}, "root", 409),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, "root", 403),
        ({"resourceVersion": "3"}, "root", 400),
        ({"resourceVersion": "3", "roles": ["x.y.z"]}, "root", 400),
        ({"resourceVersion": "3", "deletionProtection": True}, "eve", 404),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, "admin", 202),
    ],
)
async def test_update_rules(
    harness: Harness, payload: dict[str, Any], subject: str, status: int
) -> None:
    response = await harness.client.patch(
        "/v1/ipm/serviceaccounts/binder", json=payload, headers=auth(subject)
    )
    assert response.status_code == status


async def test_delete_requires_the_version_and_the_organization(harness: Harness) -> None:
    path = "/v1/ipm/serviceaccounts/binder"
    assert (await harness.client.delete(path, headers=auth("root"))).status_code == 400
    stale = await harness.client.delete(f"{path}?resourceVersion=2", headers=auth("root"))
    assert stale.status_code == 409
    other = await harness.client.delete(f"{path}?resourceVersion=3", headers=auth("eve"))
    assert other.status_code == 404
    deleted = await harness.client.delete(f"{path}?resourceVersion=3", headers=auth("bia"))
    assert deleted.status_code == 202
    data = harness.publisher.published[0][1]["data"]
    generated.ServiceAccountRequestedDeleteData.model_validate(data)


@pytest.mark.parametrize(("protected", "status"), [(True, 409), (False, 202), (None, 409)])
async def test_delete_is_refused_only_while_protected(
    harness: Harness, protected: bool | None, status: int
) -> None:
    harness.repository.resources["x"] = serviceaccount("x", protected=protected)
    response = await harness.client.delete(
        "/v1/ipm/serviceaccounts/x?resourceVersion=3", headers=auth("root")
    )
    assert response.status_code == status
    if status == 409:
        assert response.json()["errorCode"] == "DeletionProtected"


# ---------------------------------------------------------------------- chaves públicas


async def test_the_receiver_never_accepts_or_returns_private_key_material(harness: Harness) -> None:
    refused = await create(harness, "root", keys=[{**key_spec(KEY_B), "privateKey": "x"}])
    assert (refused.status_code, refused.json()["field"]) == (400, "keys.0.privateKey")
    ok = await harness.client.get("/v1/ipm/serviceaccounts/binder", headers=auth("root"))
    assert "PRIVATE" not in ok.text and "privateKey" not in ok.text


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        (
            [key_spec("-----BEGIN PUBLIC KEY-----\n" + "A" * 300 + "\n-----END PUBLIC KEY-----\n")],
            "PEM",
        ),
        ([key_spec(KEY_SMALL)], "2048"),
        ([key_spec(KEY_EC)], "RSA"),
        ([key_spec(KEY_B, NOW - timedelta(days=1))], "futuro"),
        ([key_spec(KEY_B, NOW + timedelta(days=366))], "365"),
        ([key_spec(KEY_B), key_spec(KEY_B)], "mais de uma vez"),
        ([key_spec(k) for k in (KEY_A, KEY_B, KEY_C, KEY_D)], "1 a 3"),
        ([], "1 a 3"),
    ],
)
async def test_invalid_public_keys_are_400_without_echoing_the_key(
    harness: Harness, keys: list[dict[str, str]], message: str
) -> None:
    response = await create(harness, "root", keys=keys)
    assert response.status_code == 400
    assert harness.publisher.published == []
    if keys:
        assert keys[0]["publicKey"] not in response.text
    assert message in response.text or response.json()["field"].startswith("keys")


async def test_the_fingerprint_is_the_sha256_of_the_der_and_the_pem_is_canonical(
    harness: Harness,
) -> None:
    messy = KEY_B.replace("\n", "\n")  # mesma chave: o PEM volta no formato canônico
    response = await create(harness, "root", keys=[key_spec(messy)])
    assert response.status_code == 202
    (key,) = harness.publisher.published[0][1]["data"]["specification"]["keys"]
    assert key["fingerprint"] == _fingerprint(KEY_B)
    assert key["publicKey"] == KEY_B


async def test_update_keys_requires_bind_for_a_member_and_rotates_with_the_fingerprints(
    harness: Harness,
) -> None:
    harness.repository.resources["x"] = serviceaccount("x", keys=[desired_key(KEY_A)])
    path = "/v1/ipm/serviceaccounts/x"
    rotation = {"resourceVersion": "3", "keys": [key_spec(KEY_A), key_spec(KEY_B)]}
    refused = await harness.client.patch(path, json=rotation, headers=auth("bia"))
    assert refused.status_code == 403
    accepted = await harness.client.patch(path, json=rotation, headers=auth("binder"))
    assert accepted.status_code == 202
    keys = harness.publisher.published[0][1]["data"]["specification"]["keys"]
    assert {key["fingerprint"] for key in keys} == {_fingerprint(KEY_A), _fingerprint(KEY_B)}


async def test_update_keeps_a_key_already_desired_even_when_it_has_expired(
    harness: Harness,
) -> None:
    """Reenviar a lista lida não renova nem recusa a chave antiga (`retained`)."""
    expired = NOW - timedelta(days=1)
    harness.repository.resources["x"] = serviceaccount("x", keys=[desired_key(KEY_A, expired)])
    response = await harness.client.patch(
        "/v1/ipm/serviceaccounts/x",
        json={"resourceVersion": "3", "keys": [key_spec(KEY_A, expired), key_spec(KEY_B)]},
        headers=auth("root"),
    )
    assert response.status_code == 202
    keys = harness.publisher.published[0][1]["data"]["specification"]["keys"]
    by_fingerprint = {key["fingerprint"]: key for key in keys}
    assert (
        by_fingerprint[_fingerprint(KEY_A)]["expiresAt"] == desired_key(KEY_A, expired)["expiresAt"]
    )


async def test_update_cannot_leave_the_serviceaccount_without_keys(harness: Harness) -> None:
    response = await harness.client.patch(
        "/v1/ipm/serviceaccounts/binder",
        json={"resourceVersion": "3", "keys": []},
        headers=auth("root"),
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------- reconhecimento


async def test_a_human_user_of_the_organization_acts_in_it_through_the_user_receiver(
    harness: Harness,
) -> None:
    ok = await harness.client.get(
        f"/v1/ipm/serviceaccounts?organizationId={ORG}", headers=auth("human")
    )
    assert ok.status_code == 200
    assert harness.users.calls == ["human"]
    other = await harness.client.get(
        f"/v1/ipm/serviceaccounts?organizationId={OTHER_ORG}", headers=auth("human")
    )
    assert other.status_code == 404


# ---------------------------------------------------------------------- Operation


async def test_operation_is_readable_only_by_the_requester_and_operators(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "root")
    path = "/v1/ipm/serviceaccounts/u-1/operations"
    own = await harness.client.get(f"{path}/op-1", headers=auth("root"))
    assert own.status_code == 200
    generated.Operation.model_validate(own.json())
    assert (await harness.client.get(f"{path}/op-1", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-1", headers=auth("admin"))).status_code == 200
    other = await harness.client.get(
        "/v1/ipm/serviceaccounts/u-2/operations/op-1", headers=auth("root")
    )
    assert other.status_code == 404
