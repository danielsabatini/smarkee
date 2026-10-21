"""Conformidade da telemetria de dev (decisões 0045, 0050, 0054, 0055, 0059 e 0062).

Caixa-preta: faz um cadastro pelo gateway de borda e lê os arquivos que os telemeters gravam (o da
plataforma e o de cada feature; o `telemetry-router` só roteia). Exige a plataforma de dev no ar.
O cadastro cria um usuário `conf.*@example.com`, que o `smarkee-dev-cleanup` remove.
"""

import json
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

REPOSITORY = Path(__file__).resolve().parents[3]
# Saída do platform-telemeter da plataforma (infra e o app sem telemeter próprio).
TELEMETRY_DIR = Path(
    os.environ.get(
        "CONFORMANCE_TELEMETRY_DIR", REPOSITORY / "infrastructure" / "dev" / "platform-telemeter"
    )
)
# Pastas de saída dos telemeters das features (decisão 0062): os logs de app de cada uma
# vão para a sua.
FEATURE_TELEMETRY_DIRS = [
    Path(directory)
    for directory in os.environ.get(
        "CONFORMANCE_FEATURE_TELEMETRY_DIRS",
        os.pathsep.join(
            str(REPOSITORY / "features" / module / kind / "telemeter")
            for module, kind in (("core", "account"), ("ipm", "organization"), ("sum", "service"))
        ),
    ).split(os.pathsep)
]
# Onde cada telemeter grava: o da plataforma separa `logs/app` e `logs/infra`; o de uma feature só
# recebe sinais de app, então grava direto em `logs/` e `traces/` (decisão 0062).
PLATFORM_APP_LOGS = TELEMETRY_DIR / "logs" / "app"
PLATFORM_INFRA_LOGS = TELEMETRY_DIR / "logs" / "infra"
PLATFORM_APP_METRICS = TELEMETRY_DIR / "metrics" / "app"
PLATFORM_INFRA_METRICS = TELEMETRY_DIR / "metrics" / "infra"
FEATURE_APP_LOGS = [directory / "logs" for directory in FEATURE_TELEMETRY_DIRS]
PLATFORM_TRACES = TELEMETRY_DIR / "traces"
FEATURE_TRACES = [directory / "traces" for directory in FEATURE_TELEMETRY_DIRS]
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


def read_lines(*directories: Path) -> Iterator[dict[str, Any]]:
    for directory in directories:
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield cast("dict[str, Any]", json.loads(line))


def logs(*directories: Path) -> list[Record]:
    """Registros de log achatados, lidos das pastas dadas."""
    found: list[Record] = []
    for line in read_lines(*directories):
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


def app_logs() -> list[Record]:
    """Logs de app: o arquivo compartilhado da plataforma e a pasta de cada telemeter de feature."""
    return logs(PLATFORM_APP_LOGS, *FEATURE_APP_LOGS)


def infra_logs() -> list[Record]:
    return logs(PLATFORM_INFRA_LOGS)


def spans(*directories: Path) -> list[Record]:
    """Spans do gateway de borda (padrão: o `platform-telemeter` e os das features)."""
    found: list[Record] = []
    for line in read_lines(*(directories or (PLATFORM_TRACES, *FEATURE_TRACES))):
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


def metrics(*directories: Path) -> list[Record]:
    """Pontos de dados de métricas achatados, lidos das pastas dadas."""
    found: list[Record] = []
    for line in read_lines(*(directories or (PLATFORM_INFRA_METRICS,))):
        for resource_metrics in line.get("resourceMetrics", []):
            resource = attributes_of(resource_metrics["resource"].get("attributes", []))
            for scope_metrics in resource_metrics.get("scopeMetrics", []):
                for metric in scope_metrics.get("metrics", []):
                    payload: Record = (
                        metric.get("gauge") or metric.get("sum") or metric.get("histogram") or {}
                    )
                    for point in payload.get("dataPoints", []):
                        found.append(
                            {
                                "name": metric["name"],
                                "unit": metric.get("unit", ""),
                                "resource": resource,
                                "attributes": attributes_of(point.get("attributes", [])),
                                "time_ns": int(point.get("timeUnixNano", "0")),
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
        for record in app_logs():
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
        roles = {r["role"] for r in app_logs() if r["trace_id"] == trace_id}
        return roles if roles >= ROLES_OF_THE_LOOP else None

    wait_for(f"logs de {sorted(ROLES_OF_THE_LOOP)} com o trace_id {trace_id}", roles_seen)

    gateway_spans = gateway_spans_of(trace_id)
    assert len(gateway_spans) == 1, "deve haver um só span do gateway com esse trace_id"
    assert gateway_spans[0]["parent_span_id"] == "", "o gateway inicia o trace: sem span pai"


CONTEXT_EVENTS = ("request published", "requested handled", "action published", "action handled")
OPAQUE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def test_an_anonymous_registration_carries_its_business_context_in_every_hop(
    registration: tuple[str, str],
) -> None:
    resource_id, trace_id = registration

    def events() -> list[Record] | None:
        found = [r for r in app_logs() if r["trace_id"] == trace_id and r["body"] in CONTEXT_EVENTS]
        return found if {r["body"] for r in found} >= set(CONTEXT_EVENTS) else None

    for record in wait_for(f"eventos {CONTEXT_EVENTS} do trace {trace_id}", events):
        attributes = record["attributes"]
        where = f"{record['role']}: {record['body']}"
        assert attributes.get("smarkee.actor.type") == "anonymous", where
        assert "user.id" not in attributes, f"{where}: anônimo não tem id de ator"
        assert attributes.get("smarkee.resource.id") == resource_id, where
        assert attributes.get("smarkee.operation.name") == "create", where


def test_app_logs_hold_no_email_and_every_actor_id_is_opaque(
    started_ns: int, registration: tuple[str, str]
) -> None:
    del registration
    recent = [r for r in app_logs() if r["time_ns"] >= started_ns]
    assert recent, "nenhum log de app desde o início do teste"
    for record in recent:
        values = [record["body"], *[str(v) for v in record["attributes"].values()]]
        assert not any(EMAIL.search(value) for value in values), f"e-mail em: {record['body']}"
        actor = record["attributes"].get("user.id")
        assert actor is None or OPAQUE_IDENTIFIER.match(actor), (
            "user.id deve ser identificador opaco"
        )


def test_core_account_app_logs_go_to_its_own_telemeter_and_not_to_the_shared_file(
    registration: tuple[str, str],
) -> None:
    _, trace_id = registration

    def in_the_feature() -> list[Record] | None:
        found = [r for r in logs(*FEATURE_APP_LOGS) if r["trace_id"] == trace_id]
        return found if {r["role"] for r in found} >= ROLES_OF_THE_LOOP else None

    wait_for("logs de core/account na pasta do telemeter da feature", in_the_feature)
    # Um trace atravessa features (o Manager do sum também trata o fato da conta): o log de cada uma
    # vai ao gateway do seu dono. Aqui só importa que nenhum log de core-account caiu no arquivo
    # compartilhado.
    shared = logs(PLATFORM_APP_LOGS)
    leaked = [
        r
        for r in shared
        if r["trace_id"] == trace_id and str(r["service"]).startswith("core-account")
    ]
    assert leaked == [], "log de core-account no arquivo compartilhado"


def test_core_account_spans_go_to_its_own_telemeter_and_not_to_the_platform_one(
    registration: tuple[str, str],
) -> None:
    _, trace_id = registration

    def in_the_feature() -> list[Record] | None:
        found = [s for s in spans(*FEATURE_TRACES) if s["trace_id"] == trace_id]
        return found or None

    wait_for("span de core/account na pasta do telemeter da feature", in_the_feature)
    leaked = [s for s in spans(PLATFORM_TRACES) if s["trace_id"] == trace_id]
    assert leaked == [], "span de core-account no `platform-telemeter`"


def emit_probe_log(module: str, kind: str) -> str:
    """Sobe um contêiner sintético que emite um log de app no formato do contrato (0045) da feature.

    Determinístico: um log de app só existe quando a feature está ativa, e o Observer de uma
    feature sem recursos fica calado. Devolve o marcador que o corpo do log carrega."""
    marker = uuid.uuid4().hex[:10]
    name = f"probe-route-{marker}"
    record = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "severity_number": 9,
        "severity_text": "INFO",
        "body": f"probe route {marker}",
        "scope": {"name": "probe"},
        "resource": {
            "service.name": f"{module}-{kind}-probe",
            "service.namespace": "smarkee",
            "service.instance.id": "probe-1",
            "smarkee.module": module,
            "smarkee.resource.type": kind,
            "smarkee.component.role": "manager",
        },
    }
    script = f"sleep 4; echo '{json.dumps(record)}'; sleep 20"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--log-driver",
                "json-file",
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
    return marker


def feature_prefix(telemeter: Path) -> str:
    """`<módulo>-<tipo>` da feature dona da pasta `features/<módulo>/<tipo>/telemeter`."""
    return f"{telemeter.parent.parent.name}-{telemeter.parent.name}"


# Uma rota sem token de cada feature: o gateway responde 401, e o span dela é o que o teste procura.
FEATURE_ROUTES = {
    "core-account": "/v1/core/accounts/probe",
    "ipm-organization": "/v1/ipm/organizations",
    "sum-service": "/v1/sum/services",
}


@pytest.mark.parametrize("telemeter", FEATURE_TELEMETRY_DIRS, ids=feature_prefix)
def test_each_feature_telemeter_gets_only_its_own_app_logs_and_spans(
    telemeter: Path, started_ns: int
) -> None:
    prefix = feature_prefix(telemeter)
    httpx.get(f"{API_URL}{FEATURE_ROUTES[prefix]}", headers={"Host": API_HOST}, timeout=10.0)
    route = f"{prefix}-receiver"

    marker = emit_probe_log(telemeter.parent.parent.name, telemeter.parent.name)

    def logs_arrived() -> bool | None:
        return any(marker in r["body"] for r in logs(telemeter / "logs")) or None

    def span_arrived() -> bool | None:
        found = spans(telemeter / "traces")
        return (
            any(
                s["start_ns"] >= started_ns and s["attributes"].get("apisix.service_name") == route
                for s in found
            )
            or None
        )

    wait_for(f"log sintético de {prefix} no telemeter da feature", logs_arrived)
    wait_for(f"span da rota {route} no telemeter da feature", span_arrived)

    own_logs = logs(telemeter / "logs")
    assert [r["service"] for r in own_logs if not str(r["service"]).startswith(prefix)] == []
    own_spans = spans(telemeter / "traces")
    assert {s["attributes"].get("apisix.service_name") for s in own_spans} <= {route}
    leaked_logs = [r for r in logs(PLATFORM_APP_LOGS) if marker in r["body"]]
    leaked_spans = [
        s
        for s in spans(PLATFORM_TRACES)
        if s["start_ns"] >= started_ns and s["attributes"].get("apisix.service_name") == route
    ]
    assert leaked_logs == [] and leaked_spans == [], f"sinal de {prefix} no platform-telemeter"


def test_the_feature_telemeter_configs_are_identical() -> None:
    """Os `config.yaml` dos telemeters das features não podem divergir (decisão 0062)."""
    configs = {
        directory: (directory / "config.yaml").read_text(encoding="utf-8")
        for directory in FEATURE_TELEMETRY_DIRS
    }
    assert len(set(configs.values())) == 1, f"configs divergentes: {sorted(map(str, configs))}"


def test_a_trace_context_forged_by_the_client_is_ignored() -> None:
    forged = f"00-{FORGED_TRACE_ID}-{'b' * 16}-01"
    resource_id = register({"traceparent": forged, "tracestate": "forjado=1"})
    trace_id = trace_id_of_request(resource_id)
    assert trace_id != FORGED_TRACE_ID
    assert not any(r["trace_id"] == FORGED_TRACE_ID for r in app_logs())
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
    recent = [r for r in infra_logs() if r["time_ns"] >= started_ns]
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
        f'echo "STATEMENT: orphan-sql-line {marker}"; '
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
            bodies = [r["body"] for r in infra_logs() if r["service"] == name]
            return bodies if any(f"probe {marker}" in b for b in bodies) else None

        bodies = wait_for("registro do contêiner sintético em logs/infra", probe)
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)

    joined = "\n".join(bodies)
    assert "<redacted-email>" in joined
    assert "probe.one@example.com" not in joined
    assert "missing translation" not in joined, "o WARN de tradução do Zitadel deve ser descartado"
    assert "STATEMENT:" not in joined, "linhas de infra sem severidade devem ser descartadas"


EXPECTED_INFRA_METRICS: dict[str, set[str]] = {
    "database": {
        "postgresql.backends",
        "postgresql.connection.max",
        "postgresql.commits",
        "postgresql.rollbacks",
        "postgresql.deadlocks",
        "postgresql.db_size",
        "postgresql.rows",
        "smarkee.db.outbox.unpublished_messages",
        "smarkee.db.outbox.oldest_unpublished_age",
    },
    "identity": {
        "rpc.server.duration",
        "http.server.request.duration",
        "smarkee.identity.http.requests",
        "db.client.connection.count",
        "db.client.connection.max",
        "db.client.connection.wait_time",
        "smarkee.identity.projection.events",
    },
    "messaging": {
        "smarkee.messaging.consumer.pending_messages",
        "smarkee.messaging.consumer.ack_pending_messages",
        "smarkee.messaging.consumer.redelivered_messages",
        "smarkee.messaging.stream.messages",
        "smarkee.messaging.stream.size",
        "smarkee.messaging.server.slow_consumers",
        "smarkee.messaging.server.connections",
    },
}


def test_infra_metrics_cover_database_identity_and_messaging_with_otel_semconv(
    started_ns: int,
) -> None:
    def all_services_collected() -> list[Record] | None:
        recent = [m for m in metrics(PLATFORM_INFRA_METRICS) if m["time_ns"] >= started_ns]
        by_service: dict[str, set[str]] = {service: set() for service in EXPECTED_INFRA_METRICS}
        for point in recent:
            service = str(point["resource"].get("service.name", ""))
            if service in by_service:
                by_service[service].add(point["name"])
        if all(by_service[s] >= expected for s, expected in EXPECTED_INFRA_METRICS.items()):
            return recent
        return None

    recent = wait_for(
        "métricas de infra de database, identity e messaging em metrics/infra",
        all_services_collected,
    )
    service_points = [
        m for m in recent if m["resource"].get("service.name") in EXPECTED_INFRA_METRICS
    ]
    for point in service_points:
        resource = point["resource"]
        assert resource.get("service.namespace") == "smarkee", point["name"]
        assert resource.get("deployment.environment.name") == "development", point["name"]
        assert resource.get("server.address"), point["name"]
        assert resource.get("server.port"), point["name"]
        assert resource.get("service.instance.id"), point["name"]
        assert not point["name"].startswith(("go_", "process_", "scrape_")), point["name"]
        assert point["name"] not in {"up", "target_info", "otel_scope_info"}

    row_namespaces = {
        str(m["attributes"].get("db.namespace", ""))
        for m in service_points
        if m["name"] == "postgresql.rows"
    }
    assert row_namespaces and all(ns.startswith("smarkee|") for ns in row_namespaces), (
        f"postgresql.rows deve vir apenas do banco smarkee: {row_namespaces}"
    )

    outbox_collections = {
        str(m["attributes"].get("db.collection.name", ""))
        for m in service_points
        if m["name"] == "smarkee.db.outbox.unpublished_messages"
    }
    assert {"account_outbox", "organization_outbox", "service_outbox"} <= outbox_collections

    leaked_app = [
        m["name"]
        for m in metrics(PLATFORM_APP_METRICS)
        if m["time_ns"] >= started_ns
        and (
            m["resource"].get("service.name") in EXPECTED_INFRA_METRICS
            or m["name"].startswith(("container.", "postgresql."))
        )
    ]
    assert leaked_app == [], f"métricas de infra vazaram para metrics/app: {leaked_app}"
