"""Adaptadores de I/O para banco SSOT e NATS JetStream."""

import json
from datetime import UTC, datetime
from typing import Any

import nats
import psycopg
from nats.aio.client import Client as NatsClient
from psycopg import sql

from smarkee_dev_republish.model import DesiredRecord, Kind, deterministic_message_id


class PostgresSsot:
    """Acesso ao banco SSOT em dev."""

    def __init__(self, host: str = "localhost", port: int = 5432, dbname: str = "ssot") -> None:
        self._host = host
        self._port = port
        self._dbname = dbname

    def _connect(self, role: str) -> psycopg.Connection[Any]:
        return psycopg.connect(
            f"host={self._host} port={self._port} dbname={self._dbname} "
            f"user={role} password={role} connect_timeout=3",
            autocommit=True,
        )

    @staticmethod
    def _table(name: str) -> sql.Identifier:
        schema, _, table = name.partition(".")
        return sql.Identifier(schema, table)

    def fetch_records(self, kind: Kind, resource_id: str | None = None) -> list[DesiredRecord]:
        """Lê todos os recursos vigentes da tabela e monta os envelopes desired."""
        base_query = (
            "SELECT resource_id, schema_version, lifecycle, reconciliation, "
            "desired, desired_generation FROM {table}"
        )
        params: tuple[Any, ...] = ()
        if resource_id:
            base_query += " WHERE resource_id = %s"
            params = (resource_id,)

        query = sql.SQL(base_query).format(table=self._table(kind.table))
        with self._connect(kind.manager_role) as conn:
            rows = conn.execute(query, params).fetchall()

        now = datetime.now(UTC).isoformat()
        records: list[DesiredRecord] = []
        for row in rows:
            r_id = str(row[0])
            schema_ver = str(row[1]) if row[1] else "1.0"
            lifecycle = str(row[2])
            reconciliation = str(row[3])
            desired = dict(row[4]) if isinstance(row[4], dict) else {}
            gen = int(row[5]) if row[5] is not None else 1

            msg_id = deterministic_message_id(kind.module, kind.resource_type, r_id, gen)
            subject = f"manager.desired.{kind.module}.{kind.resource_type}.{r_id}"

            payload_data = dict(desired)
            payload_data.setdefault("lifecycle", lifecycle)
            payload_data.setdefault("reconciliation", reconciliation)

            envelope = {
                "messageId": msg_id,
                "schemaVersion": schema_ver,
                "messageType": "desired",
                "emitter": "manager",
                "module": kind.module,
                "resourceType": kind.resource_type,
                "resourceId": r_id,
                "operation": "changed" if gen > 1 else "created",
                "desiredGeneration": gen,
                "requestedBy": "system:republish",
                "correlationId": deterministic_message_id(
                    kind.module, kind.resource_type, r_id, 0
                ),
                "causationId": msg_id,
                "occurredAt": now,
                "publishedAt": now,
                "data": payload_data,
            }

            records.append(
                DesiredRecord(
                    module=kind.module,
                    resource_type=kind.resource_type,
                    resource_id=r_id,
                    desired_generation=gen,
                    lifecycle=lifecycle,
                    reconciliation=reconciliation,
                    desired=desired,
                    message_id=msg_id,
                    subject=subject,
                    envelope=envelope,
                )
            )
        return records

    def enqueue_outbox(self, kind: Kind, records: list[DesiredRecord]) -> int:
        """Insere registros na tabela de outbox do tipo se ainda não existirem."""
        if not records:
            return 0
        insert_sql = sql.SQL(
            "INSERT INTO {outbox} (message_id, resource_id, subject, payload) "
            "VALUES (%s, %s, %s, %s::jsonb) "
            "ON CONFLICT (message_id) DO NOTHING"
        ).format(outbox=self._table(kind.outbox_table))

        enqueued = 0
        with self._connect(kind.manager_role) as conn:
            for rec in records:
                cursor = conn.execute(
                    insert_sql,
                    (
                        rec.message_id,
                        rec.resource_id,
                        rec.subject,
                        json.dumps(rec.envelope),
                    ),
                )
                enqueued += cursor.rowcount if cursor.rowcount > 0 else 0
        return enqueued


class NatsBus:
    """Publicador direto no NATS JetStream com Nats-Msg-Id determinístico."""

    def __init__(self, url: str = "nats://localhost:4222", password: str = "") -> None:
        self._url = url
        self._password = password
        self._client: NatsClient | None = None

    async def connect(self) -> None:
        options: dict[str, Any] = {"servers": [self._url]}
        if self._password:
            options["user"] = "smarkee"
            options["password"] = self._password
        self._client = await nats.connect(**options)  # pyright: ignore[reportUnknownMemberType]

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def publish_record(self, record: DesiredRecord) -> bool:
        """Publica um envelope com deduplicação nativa via Nats-Msg-Id."""
        if not self._client:
            raise RuntimeError("NATS client não conectado")
        headers = {"Nats-Msg-Id": record.message_id}
        payload = json.dumps(record.envelope).encode("utf-8")
        js = self._client.jetstream()  # pyright: ignore[reportUnknownMemberType]
        ack = await js.publish(record.subject, payload, headers=headers)
        return bool(ack.seq)
