"""Validação de conformidade entre os payloads gerados pelos exemplos da CLI e os JSON Schemas.

Garante que os exemplos documentados nos comandos (`sk --help`, `clig-conformance.md`)
produzam requisições HTTP estritamente compatíveis com os contratos publicados em `schemas/`.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from sk.features.bsm import account as bsm_account
from sk.features.core import account as core_account
from sk.features.ipm import group as ipm_group
from sk.features.ipm import organization as ipm_organization
from sk.features.ipm import role as ipm_role
from sk.features.ipm import serviceaccount as ipm_serviceaccount
from sk.features.ipm import user as ipm_user
from sk.features.sum import service as sum_service

SCHEMAS_ROOT = Path(__file__).resolve().parents[4] / "schemas"


def _load_schema(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _refuse_remote(uri: str) -> Resource[Any]:
    raise NoSuchResource(ref=uri)


@cache
def _registry() -> Registry[Any]:
    files = sorted(SCHEMAS_ROOT.rglob("*.schema.json"))
    return Registry(retrieve=_refuse_remote).with_resources(  # pyright: ignore[reportCallIssue]
        (path.as_uri(), Resource.from_contents(_load_schema(path))) for path in files
    )


def assert_schema_valid(schema_relative_path: str, payload: Any) -> None:
    schema_path = SCHEMAS_ROOT / schema_relative_path
    validator = Draft202012Validator(
        {**_load_schema(schema_path), "$id": schema_path.as_uri()},
        registry=_registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(payload)  # pyright: ignore[reportUnknownMemberType]


SAMPLE_RSA_PUB = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAz8Q1x4h9a8z7y6w5v4u3\n"
    "t2s1r0q9p8o7n6m5l4k3j2i1h0g9f8e7d6c5b4a3Z2Y1X0W9V8U7T6S5R4Q3P2O1\n"
    "N0M9L8K7J6I5H4G3F2E1D0C9B8A7z6y5x4w3v2u1t0s9r8q7p6o5n4m3l2k1j0i9\n"
    "h8g7f6e5d4c3b2a1Z0Y9X8W7V6U5T4S3R2Q1P0O9N8M7L6K5J4I3H2G1F0E9D8C7\n"
    "B6A5z4y3x2w1v0u9t8s7r6q5p4o3n2m1l0k9j8i7h6g5f4e3d2c1b0a9Z8Y7X6W5\n"
    "V4U3T2S1R0Q9P8O7NwIDAQAB\n"
    "-----END PUBLIC KEY-----\n"
)


def test_ipm_organization_create_payload_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "org-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.ipm.organization.call_api", fake_call_api)
    ipm_organization.create_organization(
        "https://api.smarkee.internal",
        token="test-token",
        name="acme",
        idempotency_key="idemp-1",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("ipm/organization/api-create-request.v1.schema.json", captured[0])


def test_ipm_role_create_payload_conforms_to_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "role-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.ipm.role.call_api", fake_call_api)
    ipm_role.create_role(
        "https://api.smarkee.internal",
        token="test-token",
        organization_id="01950000-0000-7000-8000-000000000001",
        name="ipm.auditor",
        description="Auditor role",
        permissions=["core.account.get", "ipm.user.get"],
        idempotency_key="idemp-1",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("ipm/role/api-create-request.v1.schema.json", captured[0])


def test_ipm_user_create_payload_conforms_to_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "usr-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.ipm.user.call_api", fake_call_api)
    ipm_user.create_user(
        "https://api.smarkee.internal",
        token="test-token",
        organization_id="01950000-0000-7000-8000-000000000001",
        email="user@acme.com",
        given_name="John",
        family_name="Doe",
        idempotency_key="idemp-1",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("ipm/user/api-create-request.v1.schema.json", captured[0])


def test_ipm_serviceaccount_create_payload_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "sa-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.ipm.serviceaccount.call_api", fake_call_api)
    ipm_serviceaccount.create_serviceaccount(
        "https://api.smarkee.internal",
        token="test-token",
        organization_id="01950000-0000-7000-8000-000000000001",
        name="ci-deploy",
        public_key=SAMPLE_RSA_PUB,
        expires_at="2027-01-01T00:00:00Z",
        idempotency_key="idemp-1",
        allow_insecure_http=True,
        description="Pipeline de deploy",
    )
    assert len(captured) == 1
    assert_schema_valid("ipm/serviceaccount/api-create-request.v1.schema.json", captured[0])


def test_ipm_group_create_payload_conforms_to_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "grp-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.ipm.group.call_api", fake_call_api)
    ipm_group.create_group(
        "https://api.smarkee.internal",
        token="test-token",
        organization_id="01950000-0000-7000-8000-000000000001",
        name="dev-team",
        description="Dev team group",
        roles=["core.accountViewer"],
        idempotency_key="idemp-1",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("ipm/group/api-create-request.v1.schema.json", captured[0])


def test_bsm_account_create_payload_conforms_to_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "bac-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.bsm.account.call_api", fake_call_api)
    bsm_account.create_account(
        "https://api.smarkee.internal",
        token="test-token",
        display_name="Acme Corp",
        billing_currency="BRL",
        billing_contacts=["finance@acme.com"],
        idempotency_key="idemp-1",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("bsm/account/api-create-request.v1.schema.json", captured[0])


def test_sum_service_enable_payload_conforms_to_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_call_api(
        method: str, url: str, path: str, *, body: dict[str, Any] | None = None, **_: Any
    ) -> tuple[int, dict[str, str]]:
        if body is not None:
            captured.append(body)
        return 202, {"resourceId": "srv-1", "operationId": "op-1"}

    monkeypatch.setattr("sk.features.sum.service.call_api", fake_call_api)
    sum_service.enable_service(
        "https://api.smarkee.internal",
        token="test-token",
        service="ipm",
        idempotency_key="idemp-1",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("sum/service/api-create-request.v1.schema.json", captured[0])


def test_core_account_registration_payload_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class FakeResponse:
        status = 202

        def read(self) -> bytes:
            return json.dumps({"resourceId": "acc-1", "operationId": "op-1"}).encode()

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_: Any) -> None:
            pass

    def fake_urlopen(request: Any, timeout: float = 0) -> FakeResponse:
        data = getattr(request, "data", None)
        if data:
            captured.append(json.loads(data))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    core_account.submit_registration(
        "https://api.smarkee.internal",
        given_name="Ana",
        family_name="Souza",
        email="ana@example.com",
        allow_insecure_http=True,
    )
    assert len(captured) == 1
    assert_schema_valid("core/account/api-create-request.v1.schema.json", captured[0])
