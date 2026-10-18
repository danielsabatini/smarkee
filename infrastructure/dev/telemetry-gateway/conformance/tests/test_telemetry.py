"""Conformidade da telemetria de dev (decisões 0045, 0050, 0054, 0055 e 0059).

Caixa-preta: faz um cadastro pelo gateway e lê os arquivos que o `telemetry-gateway` grava. Exige a
plataforma de dev no ar. O cadastro cria um usuário `conf.*@example.com`, que o
`smarkee-dev-cleanup` remove.
"""

import json
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

TELEMETRY_DIR = Path(
    os.environ.get("CONFORMANCE_TELEMETRY_DIR", Path(__file__).resolve().parents[2])
)
API_URL = os.environ.get("CONFORMANCE_API_URL", "http://localhost:8080")
API_HOST = os.environ.get("CONFORMANCE_API_HOST", "api-dev.smarkee.com.br")
WAIT_SECONDS = 90.0
ROLES_OF_THE_LOOP = {"receiver", "manager", "publisher", "reconciler", "executor"}
ACCEPTED = 202
TOO_MANY_REQUESTS = 429
FORGED_TRACE_ID = "a" * 32
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
VERIFICATION_CODE = re.compile(r"Code:[A-Z0-9]{6}\b")

Record = dict[str, Any]


def attributes_of(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: next(iter(item["value"].values())) for item in items}


def read_lines(subdirectory: str) -> Iterator[dict[str, Any]]:
    for path in sorted((TELEMETRY_DIR / subdirectory).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield cast("dict[str, Any]", json.loads(line))


def logs(subdirectory: str) -> list[Record]:
    """Registros de log (`logs/app` ou `logs/infra`) já achatados."""
    found: list[Record] = []
    for line in read_lines(subdirectory):
        for resource_logs in line.get("resourceLogs", []):
            resource = attributes_of(resource_logs["resource"].get("attributes", []))
            for scope_logs in resource_logs.get("scopeLogs", []):
                for record in scope_logs.get("logRecords", []):
                    found.append(
                        {
                            "service": resource.get("service.name"),
                            "role": resource.get("smarkee.component.role"),
                            "body": record.get("body", {}).get("stringValue", ""),
                            "trace_id": record.get("traceId", ""),
                            "attributes": attributes_of(record.get("attributes", [])),
                            "time_ns": int(record.get("timeUnixNano", "0")),
                        }
                    )
    return found


def spans() -> list[Record]:
    found: list[Record] = []
    for line in read_lines("traces"):
        for resource_spans in line.get("resourceSpans", []):
            for scope_spans in resource_spans.get("scopeSpans", []):
                for span in scope_spans.get("spans", []):
                    found.append(
                        {
                            "trace_id": span["traceId"],
                            "parent_span_id": span.get("parentSpanId", ""),
                            "attributes": attributes_of(span.get("attributes", [])),
                            "start_ns": int(span.get("startTimeUnixNano", "0")),
                        }
                    )
    return found


def wait_for[T](description: str, probe: Callable[[], T | None]) -> T:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        found = probe()
        if found is not None:
            return found
        time.sleep(2.0)
    pytest.fail(f"tempo esgotado ({WAIT_SECONDS:.0f} s): {description}")


@pytest.fixture(scope="module", autouse=True)
def platform_is_up() -> None:
    if not (TELEMETRY_DIR / "traces").is_dir():
        pytest.skip(f"pasta de telemetria não encontrada: {TELEMETRY_DIR}")
    try:
        httpx.get(f"{API_URL}/health/live", headers={"Host": API_HOST}, timeout=5.0)
    except httpx.HTTPError:
        pytest.skip(f"gateway indisponível em {API_URL}")


@pytest.fixture(scope="module", autouse=True)
def started_ns() -> int:
    return time.time_ns() - 2_000_000_000


def register(headers: dict[str, str]) -> str:
    """Cadastro anônimo pelo gateway; devolve o `resourceId`. Repete se o limite de taxa recusar."""
    body = {
        "givenName": "Conformidade",
        "familyName": "Telemetria",
        "email": f"conf.telemetry-{uuid.uuid4().hex[:10]}@example.com",
    }
    for _ in range(3):
        response = httpx.post(
            f"{API_URL}/v1/core/accounts",
            json=body,
            headers={"Host": API_HOST, **headers},
            timeout=20.0,
        )
        if response.status_code == TOO_MANY_REQUESTS:
            time.sleep(float(response.headers.get("Retry-After", "5")))
            continue
        assert response.status_code == ACCEPTED, response.text
        return cast("str", response.json()["resourceId"])
    pytest.fail("o gateway recusou o cadastro com 429 três vezes")


def trace_id_of_request(resource_id: str) -> str:
    def probe() -> str | None:
        for record in logs("logs/app"):
            if (
                record["body"] == "request published"
                and record["attributes"].get("smarkee.resource.id") == resource_id
                and record["trace_id"]
            ):
                return cast("str", record["trace_id"])
        return None

    return wait_for(f"log 'request published' do recurso {resource_id}", probe)


def gateway_spans_of(trace_id: str) -> list[Record]:
    """Spans do gateway desse trace_id. O APISIX exporta os spans em lote, depois dos logs."""

    def probe() -> list[Record] | None:
        found = [
            s
            for s in spans()
            if s["trace_id"] == trace_id
            and s["attributes"].get("http.route") == "/v1/core/accounts"
            and s["attributes"].get("http.request.method") == "POST"
        ]
        return found or None

    return wait_for(f"span do gateway com o trace_id {trace_id}", probe)


@pytest.fixture(scope="module")
def registration() -> tuple[str, str]:
    """(resourceId, trace_id) de um cadastro comum."""
    resource_id = register({})
    return resource_id, trace_id_of_request(resource_id)


def test_the_trace_of_the_gateway_reaches_every_role_of_the_loop(
    registration: tuple[str, str],
) -> None:
    _, trace_id = registration

    def roles_seen() -> set[str] | None:
        roles = {r["role"] for r in logs("logs/app") if r["trace_id"] == trace_id}
        return roles if roles >= ROLES_OF_THE_LOOP else None

    wait_for(f"logs de {sorted(ROLES_OF_THE_LOOP)} com o trace_id {trace_id}", roles_seen)

    gateway_spans = gateway_spans_of(trace_id)
    assert len(gateway_spans) == 1, "deve haver um só span do gateway com esse trace_id"
    assert gateway_spans[0]["parent_span_id"] == "", "o gateway inicia o trace: sem span pai"


def test_a_trace_context_forged_by_the_client_is_ignored() -> None:
    forged = f"00-{FORGED_TRACE_ID}-{'b' * 16}-01"
    resource_id = register({"traceparent": forged, "tracestate": "forjado=1"})
    trace_id = trace_id_of_request(resource_id)
    assert trace_id != FORGED_TRACE_ID
    assert not any(r["trace_id"] == FORGED_TRACE_ID for r in logs("logs/app"))
    assert not any(s["trace_id"] == FORGED_TRACE_ID for s in spans())


def test_spans_keep_no_sensitive_request_data(
    started_ns: int, registration: tuple[str, str]
) -> None:
    gateway_spans_of(registration[1])  # o cadastro já aconteceu e o lote de spans já foi gravado
    recent = [s for s in spans() if s["start_ns"] >= started_ns]
    assert recent, "nenhum span desde o início do teste"
    for span in recent:
        attributes = span["attributes"]
        assert not {"args", "http.target", "url.full"} & set(attributes)
        query = attributes.get("url.query")
        if query:
            values = [pair.partition("=")[2] for pair in query.split("&")]
            assert set(values) <= {"REDACTED", ""}, "url.query deve ter todos os valores redigidos"


def test_infra_logs_hold_no_email_or_verification_code(
    started_ns: int, registration: tuple[str, str]
) -> None:
    del registration
    recent = [r for r in logs("logs/infra") if r["time_ns"] >= started_ns]
    leaks = [
        r["service"]
        for r in recent
        if EMAIL.search(r["body"]) or VERIFICATION_CODE.search(r["body"])
    ]
    assert leaks == [], f"logs de infra com e-mail ou código de verificação: {leaks}"


def test_the_agent_redacts_an_email_and_drops_the_zitadel_translation_warning() -> None:
    """Prova determinística, sem depender do Zitadel: um contêiner sintético de infra."""
    name = f"probe-redact-{uuid.uuid4().hex[:6]}"
    marker = uuid.uuid4().hex[:8]
    script = (
        "sleep 4; "
        f'echo "time=\\"2026-10-18T21:00:00Z\\" level=warning msg=\\"probe {marker}\\" '
        f'who=probe.one@example.com"; '
        f'echo "time=\\"2026-10-18T21:00:01Z\\" level=warning msg=\\"missing translation\\" '
        f'args=\\"map[Code:ZZZ999 LastEmail:probe.two@example.com] {marker}\\""; '
        "sleep 20"
    )
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--log-driver",
                "json-file",
                "--log-opt",
                "labels=com.docker.compose.service,smarkee.layer",
                "--label",
                "smarkee.layer=infra",
                "--label",
                f"com.docker.compose.service={name}",
                "alpine",
                "sh",
                "-c",
                script,
            ],
            check=True,
            capture_output=True,
        )
    except OSError, subprocess.CalledProcessError:
        pytest.skip("docker indisponível")

    try:

        def probe() -> list[str] | None:
            bodies = [r["body"] for r in logs("logs/infra") if r["service"] == name]
            return bodies if any(f"probe {marker}" in b for b in bodies) else None

        bodies = wait_for("registro do contêiner sintético em logs/infra", probe)
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)

    joined = "\n".join(bodies)
    assert "<redacted-email>" in joined
    assert "probe.one@example.com" not in joined
    assert "missing translation" not in joined, "o WARN de tradução do Zitadel deve ser descartado"
