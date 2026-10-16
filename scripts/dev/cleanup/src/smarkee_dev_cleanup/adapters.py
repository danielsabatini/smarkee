"""Adaptadores reais do ambiente de dev: Zitadel, PostgreSQL, NATS e Mailpit."""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import jwt
import psycopg
from psycopg import sql

from smarkee_dev_cleanup.model import ACCOUNTS, MAIL_QUERIES, STREAM_SUBJECTS, Kind, Row

HTTP_NOT_FOUND = 404


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


class ZitadelIdentity:
    """API v2 do Zitadel, com a chave da conta `platform-bootstrap` (lida na memória)."""

    ISSUER = "http://ipm-dev.smarkee.com.br:8080"
    BASE_URL = "http://localhost:8080"

    def __init__(self, key: dict[str, str], client: httpx.Client | None = None) -> None:
        host = self.ISSUER.removeprefix("http://")
        self._client = client or httpx.Client(timeout=20.0)
        self._client.headers["Host"] = host
        self._client.headers["Authorization"] = f"Bearer {self._token(key, host)}"
        self._client.headers["Connect-Protocol-Version"] = "1"

    def _token(self, key: dict[str, str], host: str) -> str:
        now = int(time.time())
        claims = {
            "iss": key["userId"],
            "sub": key["userId"],
            "aud": self.ISSUER,
            "iat": now,
            "exp": now + 300,
        }
        assertion = jwt.encode(claims, key["key"], algorithm="RS256", headers={"kid": key["keyId"]})
        response = httpx.post(
            f"{self.BASE_URL}/oauth/v2/token",
            headers={"Host": host},
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "scope": "openid urn:zitadel:iam:org:project:id:zitadel:aud",
                "assertion": assertion,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        return str(response.json()["access_token"])

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(f"{self.BASE_URL}{path}", json=body)
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())

    def organizations(self) -> dict[str, str]:
        found = self._post(
            "/zitadel.org.v2.OrganizationService/ListOrganizations", {"query": {"limit": 1000}}
        ).get("result", [])
        return {
            _text(item["id"]): _text(item["name"]) for item in cast("list[dict[str, Any]]", found)
        }

    def register_users(self) -> dict[str, str]:
        register = next((i for i, name in self.organizations().items() if name == "register"), None)
        if register is None:
            return {}
        found = self._post(
            "/v2/users",
            {
                "query": {"limit": 1000},
                "queries": [{"organizationIdQuery": {"organizationId": register}}],
            },
        ).get("result", [])
        users: dict[str, str] = {}
        for item in cast("list[dict[str, Any]]", found):
            human = cast("dict[str, Any]", item.get("human") or {})
            email = _text(cast("dict[str, Any]", human.get("email") or {}).get("email"))
            users[_text(item["userId"])] = email or _text(item.get("username"))
        return users

    def delete_organization(self, organization_id: str) -> None:
        response = self._client.delete(f"{self.BASE_URL}/v2/organizations/{organization_id}")
        response.raise_for_status()

    def delete_user(self, user_id: str) -> None:
        response = self._client.delete(f"{self.BASE_URL}/v2/users/{user_id}")
        if response.status_code != HTTP_NOT_FOUND:  # já removido é sucesso
            response.raise_for_status()


class PostgresSsot:
    """SSOT de dev, pelos papéis de login de cada módulo (senha trivial igual ao nome do papel)."""

    HOST = "localhost"
    PORT = 5432

    def _connect(self, role: str) -> psycopg.Connection[Any]:
        return psycopg.connect(
            f"host={self.HOST} port={self.PORT} dbname=smarkee user={role} password={role} "
            "connect_timeout=3",
            autocommit=True,
        )

    @staticmethod
    def _table(name: str) -> sql.Identifier:
        schema, _, table = name.partition(".")
        return sql.Identifier(schema, table)

    def rows(self, kind: Kind) -> list[Row]:
        query = sql.SQL(
            "SELECT resource_id, coalesce(desired ->> {label}, '') FROM {table}"
        ).format(label=sql.Literal(kind.label_field), table=self._table(kind.table))
        with self._connect(kind.manager_role) as connection:
            found = connection.execute(query).fetchall()
        return [Row(str(row[0]), str(row[1])) for row in found]

    def delete(self, kind: Kind, resource_ids: set[str]) -> None:
        ids = sorted(resource_ids)
        delete = sql.SQL("DELETE FROM {table} WHERE resource_id = ANY(%s)")
        with self._connect(kind.manager_role) as manager:
            manager.execute(delete.format(table=self._table(kind.table)), (ids,))
        with self._connect(kind.maintenance_role) as maintenance:
            for table in kind.support_tables:
                maintenance.execute(delete.format(table=self._table(table)), (ids,))


class NatsBus:
    """JetStream de dev: lê o `updated`, pede remoção como o Receiver faria e limpa os Subjects."""

    def __init__(self, jetstream: Any) -> None:
        self._js = jetstream

    @staticmethod
    def _subject(prefix: str, kind: Kind, resource_id: str, tail: str = "changed") -> str:
        return f"{prefix}.{kind.module}.{kind.resource_type}.{resource_id}.{tail}"

    async def _updated(self, kind: Kind, resource_id: str) -> dict[str, Any]:
        try:
            raw = await self._js.get_last_msg(
                "UPDATED", self._subject("manager.updated", kind, resource_id)
            )
        except Exception:  # sem mensagem (ou já removida): não há o que ler
            return {}
        document = json.loads(raw.data or b"{}")
        message = cast("dict[str, Any]", document) if isinstance(document, dict) else {}
        return cast("dict[str, Any]", message.get("data") or {})

    async def last_version(self, kind: Kind, resource_id: str) -> tuple[str, str] | None:
        data = await self._updated(kind, resource_id)
        if not data or data.get("removed"):
            return None
        return _text(data.get("phase")), _text(data.get("resourceVersion"))

    async def request_deletion(self, kind: Kind, resource_id: str, version: str) -> None:
        now = datetime.now(UTC).isoformat()
        message = {
            "messageId": str(uuid.uuid7()),
            "schemaVersion": "1.0",
            "messageType": "requested",
            "emitter": "receiver",
            "module": kind.module,
            "resourceType": kind.resource_type,
            "resourceId": resource_id,
            "operation": "delete",
            "requestedBy": resource_id if kind is ACCOUNTS else "cleanup",
            "correlationId": str(uuid.uuid7()),
            "occurredAt": now,
            "publishedAt": now,
            "data": {
                "operationId": str(uuid.uuid7()),
                "requestDigest": "0" * 64,
                "resourceVersion": version,
            },
        }
        await self._js.publish(
            self._subject("receiver.requested", kind, resource_id, "delete"),
            json.dumps(message).encode(),
            headers={"Nats-Msg-Id": message["messageId"]},
        )

    async def removed(self, kind: Kind, resource_id: str) -> bool:
        return bool((await self._updated(kind, resource_id)).get("removed"))

    async def purge(self, kind: Kind, resource_ids: set[str]) -> None:
        for resource_id in sorted(resource_ids):
            for stream, prefix in STREAM_SUBJECTS:
                base = f"{prefix}.{kind.module}.{kind.resource_type}.{resource_id}"
                filters = [f"{base}.>"]
                if stream == "RESULT":  # `failed` não tem o token da operação
                    filters.append(base)
                for subject in filters:
                    await self._js.purge_stream(stream, subject=subject)


class MailpitMail:
    URL = "http://localhost:8025"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=self.URL, timeout=10.0)

    def count(self) -> int:
        total = 0
        for query in MAIL_QUERIES:
            response = self._client.get("/api/v1/search", params={"query": query})
            response.raise_for_status()
            total += int(response.json().get("messages_count", 0))
        return total

    def delete(self) -> None:
        for query in MAIL_QUERIES:
            self._client.delete("/api/v1/search", params={"query": query}).raise_for_status()
