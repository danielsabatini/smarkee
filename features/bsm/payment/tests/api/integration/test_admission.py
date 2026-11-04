"""Admissão síncrona de `bsm.payment` contra o SSOT real (decisão 0098)."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from support_api import connect, unique_suffix

from bsm_payment.api.domain.admission import Admission
from bsm_payment.api.domain.errors import ApiError
from bsm_payment.api.http.admission import admit
from bsm_payment.api.store.admission import SsotAdmissionStore

Connection = psycopg.AsyncConnection[Any]
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
REQUESTER = "test-" + unique_suffix()


def specification(name: str = "Cartao Teste") -> dict[str, Any]:
    return {
        "customerAccountId": REQUESTER,
        "displayName": name,
        "provider": "mercadopago",
        "methodType": "credit_card",
        "providerToken": "sim_visa_4242",
    }


def admission(
    operation: str, resource_id: str, *, key: str | None = None, **fields: Any
) -> Admission:
    digest = hashlib.sha256(f"{operation}{resource_id}{fields}".encode()).hexdigest()
    return Admission(
        operation=operation,  # type: ignore[arg-type]
        resource_id=resource_id,
        requested_by=REQUESTER,
        correlation_id=str(uuid.uuid7()),
        request_digest=digest,
        now=NOW,
        message_id=str(uuid.uuid7()),
        idempotency_key=key,
        **fields,
    )


async def outbox_of(resource_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Lê o outbox com o papel de manutenção (a API só insere)."""
    maintenance = await connect("bsm_maintenance_login")
    try:
        cursor = await maintenance.execute(
            "SELECT subject, payload FROM bsm.payment_outbox"
            " WHERE resource_id = %s ORDER BY sequence ASC",
            (resource_id,),
        )
        rows = await cursor.fetchall()
        return [(str(subject), dict(payload)) for subject, payload in rows]
    finally:
        await maintenance.close()


async def test_create_records_payment_and_outbox_atomically(
    api_conn: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    adm = admission("create", resource_id, specification=specification("Cartao 1"))

    record = await admit(store, adm)
    assert record.resource_id == resource_id
    assert record.desired_generation == 1
    assert record.observed_generation is None
    assert record.phase == "Pending"

    outbox = await outbox_of(resource_id)
    assert len(outbox) == 1
    assert outbox[0][0] == f"desired.bsm.payment.{resource_id}"
    assert outbox[0][1]["data"]["displayName"] == "Cartao 1"


async def test_update_modifies_payment_and_records_new_outbox(
    api_conn: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    await admit(store, admission("create", resource_id, specification=specification("Cartao 1")))

    adm_update = admission(
        "update",
        resource_id,
        resource_version=1,
        specification={"displayName": "Cartao Alterado"},
    )
    record = await admit(store, adm_update)
    assert record.desired_generation == 2
    assert record.resource_version == 2
    assert record.desired["displayName"] == "Cartao Alterado"

    outbox = await outbox_of(resource_id)
    assert len(outbox) == 2
    assert outbox[1][1]["data"]["displayName"] == "Cartao Alterado"


async def test_delete_sets_absent_and_deleting_and_publishes_outbox(
    api_conn: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    await admit(store, admission("create", resource_id, specification=specification("Cartao Del")))
    await admit(
        store,
        admission(
            "update",
            resource_id,
            resource_version=1,
            specification={"deletionProtection": False},
        ),
    )

    record = await admit(
        store,
        admission(
            "delete",
            resource_id,
            resource_version=2,
        ),
    )
    assert record.phase == "Deleting"
    assert record.lifecycle == "absent"

    outbox = await outbox_of(resource_id)
    assert len(outbox) == 3
    assert outbox[2][1]["data"]["lifecycle"] == "absent"


async def test_idempotency_returns_same_record_without_duplicating_outbox(
    api_conn: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    key = "idem-" + unique_suffix()
    adm = admission("create", resource_id, key=key, specification=specification("Cartao Idem"))

    first = await admit(store, adm)
    second = await admit(store, adm)
    assert first.resource_id == second.resource_id
    assert len(await outbox_of(resource_id)) == 1


async def test_idempotency_key_reuse_with_other_content_is_rejected(
    api_conn: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    key = "idem-" + unique_suffix()
    adm = admission("create", resource_id, key=key, specification=specification("Cartao A"))
    await admit(store, adm)

    adm_other = admission("create", resource_id, key=key, specification=specification("Cartao B"))
    with pytest.raises(ApiError) as exc:
        await admit(store, adm_other)
    assert exc.value.error_code == "IdempotencyKeyReused"


async def test_api_cannot_delete_from_payment_or_truncate_tables(
    api_conn: Connection, cleanup: list[str]
) -> None:
    with pytest.raises(InsufficientPrivilege):
        await api_conn.execute("DELETE FROM bsm.payment WHERE resource_id = 'qualquer'")
    with pytest.raises(InsufficientPrivilege):
        await api_conn.execute("TRUNCATE bsm.payment")
