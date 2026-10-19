import ast
import json
import logging
import re
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from core_account_observer.logging_config import (
    EVENT_NAME_KEY,
    JsonFormatter,
    bind_context,
    bind_message_context,
    bind_traceparent,
    build_resource,
    current_traceparent,
    restore_context,
    save_context,
)

_PACKAGE = "core_account_observer"
_LOGGER_METHODS = {"debug", "info", "warning", "error", "critical", "exception", "log"}
_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[6] / "schemas" / "observability" / "log-record.v1.schema.json"
)
_SCHEMA = cast(dict[str, Any], json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))
_VALIDATOR = Draft202012Validator(_SCHEMA)
_ATTRIBUTES_SCHEMA = cast(dict[str, Any], _SCHEMA["properties"]["attributes"])
_ALLOWED_ATTRIBUTES = {
    name for name, rule in _ATTRIBUTES_SCHEMA["properties"].items() if rule is not False
}
_ATTRIBUTE_PATTERNS = [re.compile(pattern) for pattern in _ATTRIBUTES_SCHEMA["patternProperties"]]


def record(
    message: str,
    *,
    level: int = logging.INFO,
    error: Exception | None = None,
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    exc_info = None
    if error is not None:
        try:
            raise error
        except Exception as raised:
            exc_info = (type(raised), raised, raised.__traceback__)
    log_record = logging.LogRecord(f"{_PACKAGE}.test", level, __file__, 10, message, (), exc_info)
    for key, value in (extra or {}).items():
        setattr(log_record, key, value)
    return log_record


def format_line(log_record: logging.LogRecord) -> dict[str, Any]:
    """Formata o registro e exige que a linha cumpra o schema `log-record.v1`."""
    line = JsonFormatter(build_resource()).format(log_record)
    assert "\n" not in line
    payload = cast(dict[str, Any], json.loads(line))
    _VALIDATOR.validate(payload)  # pyright: ignore[reportUnknownMemberType]
    return payload


def attributes_of(payload: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], payload.get("attributes", {}))


def own_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """Atributos sem o `system` que o Observer recebe por padrão (ele nunca tem solicitante)."""
    attributes = dict(attributes_of(payload))
    if _PACKAGE.endswith("_observer") and attributes.get("smarkee.actor.type") == "system":
        del attributes["smarkee.actor.type"]
    return attributes


def test_event_is_one_json_line_with_the_log_record_fields() -> None:
    payload = format_line(record("requested handled", extra={"smarkee.outcome": "accepted"}))
    assert payload["body"] == "requested handled"
    assert payload["severity_number"] == 9
    assert payload["severity_text"] == "INFO"
    assert payload["scope"] == {"name": f"{_PACKAGE}.test"}
    assert own_attributes(payload) == {"smarkee.outcome": "accepted"}
    assert "event_name" not in payload


@pytest.mark.parametrize(
    ("level", "number", "text"),
    [
        (logging.DEBUG, 5, "DEBUG"),
        (logging.INFO, 9, "INFO"),
        (logging.WARNING, 13, "WARN"),
        (logging.ERROR, 17, "ERROR"),
        (logging.CRITICAL, 21, "FATAL"),
        (5, 1, "TRACE"),
    ],
)
def test_severity_follows_the_log_data_model(level: int, number: int, text: str) -> None:
    payload = format_line(record("x", level=level))
    assert (payload["severity_number"], payload["severity_text"]) == (number, text)


def test_terminal_color_message_added_by_uvicorn_is_not_an_attribute() -> None:
    log_record = record("Started server", extra={"color_message": "\x1b[36mStarted\x1b[0m"})
    payload = format_line(log_record)
    assert not own_attributes(payload)


def test_event_name_is_a_field_and_none_values_are_omitted() -> None:
    payload = format_line(
        record("x", extra={EVENT_NAME_KEY: "smarkee.message.rejected", "smarkee.reason": None})
    )
    assert payload["event_name"] == "smarkee.message.rejected"
    assert not own_attributes(payload)


def test_exception_message_is_never_logged_because_it_may_carry_values() -> None:
    log_record = record("falha", error=ValueError("Key (email)=(ana@example.com) already exists"))
    payload = format_line(log_record)
    attributes = payload["attributes"]
    assert attributes["error.type"] == "ValueError"
    assert attributes["exception.type"] == "ValueError"
    assert {"code.file.path", "code.line.number", "code.function.name"} <= attributes.keys()
    assert "ana@example.com" not in json.dumps(payload)


def test_exception_type_is_qualified_unless_builtin() -> None:
    payload = format_line(record("x", error=json.JSONDecodeError("m", "d", 0)))
    assert payload["attributes"]["error.type"] == "json.decoder.JSONDecodeError"


def test_resource_identifies_the_component_from_the_package_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARKEE_ENVIRONMENT", "stg")
    resource = build_resource()
    module, resource_type, role = _PACKAGE.split("_")
    assert resource["service.name"] == _PACKAGE.replace("_", "-")
    assert resource["smarkee.module"] == module
    assert resource["smarkee.resource.type"] == resource_type
    assert resource["smarkee.component.role"] == role
    assert resource["deployment.environment.name"] == "staging"


@pytest.mark.parametrize("value", [None, "", "qa"])
def test_unknown_environment_is_omitted(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.delenv("SMARKEE_ENVIRONMENT", raising=False)
    if value is not None:
        monkeypatch.setenv("SMARKEE_ENVIRONMENT", value)
    assert "deployment.environment.name" not in build_resource()


def _extra_keys(tree: ast.AST) -> list[tuple[int, ast.expr | None]]:
    keys: list[tuple[int, ast.expr | None]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _LOGGER_METHODS:
            continue
        for keyword in node.keywords:
            if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
                keys.extend((node.lineno, key) for key in keyword.value.keys)
    return keys


def _is_allowed_key(key: ast.expr | None) -> bool:
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        return False
    name = key.value
    return (
        name == EVENT_NAME_KEY
        or name in _ALLOWED_ATTRIBUTES
        or any(pattern.fullmatch(name) for pattern in _ATTRIBUTE_PATTERNS)
    )


def test_log_context_keys_are_attributes_allowed_by_the_schema() -> None:
    """Toda chave de `extra` dos loggers é um atributo que o schema aceita, ou o evento."""
    invalid: list[str] = []
    for path in _SOURCE_ROOT.rglob("*.py"):
        if path.name == "logging_config.py":
            continue
        for line, key in _extra_keys(ast.parse(path.read_text(encoding="utf-8"))):
            if not _is_allowed_key(key):
                invalid.append(f"{path.relative_to(_SOURCE_ROOT)}:{line}")
    assert invalid == []


_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def test_bound_traceparent_adds_trace_id_and_flags_to_every_log() -> None:
    assert bind_traceparent(_TRACEPARENT) == _TRACEPARENT
    try:
        payload = format_line(record("with trace"))
        assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert payload["trace_flags"] == 1
        assert "span_id" not in payload
        assert current_traceparent() == _TRACEPARENT
    finally:
        bind_traceparent(None)
    assert "trace_id" not in format_line(record("without trace"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "garbage",
        "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
        "00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-extra",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01\n",
    ],
)
def test_invalid_traceparent_is_dropped_and_clears_the_context(value: str) -> None:
    bind_traceparent(_TRACEPARENT)
    assert bind_traceparent(value) is None
    assert current_traceparent() is None
    assert "trace_id" not in format_line(record("invalid"))


def test_the_request_context_adds_actor_resource_and_action_to_every_log() -> None:
    bind_traceparent(None)
    bind_context(requested_by="01a1506e-93bc-72c9", resource_id="res-1", operation="create")
    try:
        attributes = attributes_of(format_line(record("any event")))
    finally:
        bind_traceparent(None)
    assert attributes["user.id"] == "01a1506e-93bc-72c9"
    assert attributes["smarkee.actor.type"] == "user"
    assert attributes["smarkee.resource.id"] == "res-1"
    assert attributes["smarkee.operation.name"] == "create"
    assert "smarkee.owner.id" not in attributes  # sem dono, o atributo é omitido


def test_an_anonymous_request_has_the_anonymous_type_and_no_user_id() -> None:
    bind_traceparent(None)
    bind_context(requested_by="anonymous", resource_id="res-1", operation="create")
    try:
        attributes = attributes_of(format_line(record("any event")))
    finally:
        bind_traceparent(None)
    assert attributes["smarkee.actor.type"] == "anonymous"
    assert "user.id" not in attributes


@pytest.mark.parametrize("value", ["ana@example.com", "Ana Souza", "a.b", "", "x" * 129])
def test_an_actor_that_is_not_an_opaque_identifier_is_dropped_and_never_logged(value: str) -> None:
    bind_traceparent(None)
    bind_context(requested_by=value)
    try:
        line = format_line(record("any event"))
    finally:
        bind_traceparent(None)
    assert "user.id" not in attributes_of(line)
    assert "smarkee.actor.type" not in own_attributes(line)
    assert value not in json.dumps(line) or value == ""


def test_what_the_event_states_prevails_over_the_context() -> None:
    bind_traceparent(None)
    bind_context(resource_id="from-context", operation="update")
    try:
        attributes = attributes_of(
            format_line(record("event", extra={"smarkee.resource.id": "from-event"}))
        )
    finally:
        bind_traceparent(None)
    assert attributes["smarkee.resource.id"] == "from-event"
    assert attributes["smarkee.operation.name"] == "update"


def test_binding_a_new_traceparent_starts_a_clean_context() -> None:
    bind_context(requested_by="user-1", resource_id="res-1")
    bind_traceparent(_TRACEPARENT)
    try:
        payload = format_line(record("event"))
    finally:
        bind_traceparent(None)
    assert not own_attributes(payload)  # o contexto anterior foi descartado
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_the_message_context_comes_from_the_envelope() -> None:
    envelope = {
        "module": "ipm",
        "resourceType": "organization",
        "resourceId": "org-1",
        "operation": "create",
        "requestedBy": "user-1",
        "data": {"ownerAccountId": "owner-1"},
    }
    bind_traceparent(_TRACEPARENT)
    bind_message_context(json.dumps(envelope).encode())
    try:
        payload = format_line(record("event"))
    finally:
        bind_traceparent(None)
    attributes = attributes_of(payload)
    assert attributes["smarkee.resource.id"] == "org-1"
    assert attributes["smarkee.organization.id"] == "org-1"  # o resourceId da Organization
    assert attributes["smarkee.owner.id"] == "owner-1"
    assert attributes["user.id"] == "user-1"
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"  # o trace foi mantido


def test_a_message_without_a_requester_is_a_system_actor() -> None:
    bind_traceparent(None)
    bind_message_context({"emitter": "manager", "resourceId": "res-1", "operation": "changed"})
    try:
        attributes = attributes_of(format_line(record("event")))
    finally:
        bind_traceparent(None)
    assert attributes["smarkee.actor.type"] == "system"
    assert "user.id" not in attributes


def test_a_message_with_a_requester_is_not_a_system_actor() -> None:
    bind_traceparent(None)
    bind_message_context({"requestedBy": "user-1", "resourceId": "res-1", "emitter": "observer"})
    try:
        attributes = attributes_of(format_line(record("event")))
    finally:
        bind_traceparent(None)
    assert attributes["smarkee.actor.type"] == "user"


def test_a_saved_context_can_be_restored_after_a_temporary_one() -> None:
    bind_traceparent(_TRACEPARENT)
    bind_context(requested_by="user-1", resource_id="res-1")
    saved = save_context()
    try:
        bind_traceparent(None)  # um contexto temporário, como o do `evaluate` do Reconciler
        assert current_traceparent() is None
        restore_context(saved)
        payload = format_line(record("event"))
    finally:
        bind_traceparent(None)
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert attributes_of(payload)["user.id"] == "user-1"


@pytest.mark.parametrize("message", [b"not json", b"[1, 2]", "42", {"data": "x", "resourceId": 7}])
def test_an_unreadable_message_never_breaks_logging(message: Any) -> None:
    bind_traceparent(None)
    bind_message_context(message)
    format_line(record("event"))


def test_the_observer_is_a_system_actor_even_without_context() -> None:
    bind_traceparent(None)
    resource = {**build_resource(), "smarkee.component.role": "observer"}
    line = cast(dict[str, Any], json.loads(JsonFormatter(resource).format(record("event"))))
    _VALIDATOR.validate(line)  # pyright: ignore[reportUnknownMemberType]
    assert attributes_of(line)["smarkee.actor.type"] == "system"
