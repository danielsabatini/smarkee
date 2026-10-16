import ast
import json
import logging
import re
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from ipm_organization_publisher.logging_config import EVENT_NAME_KEY, JsonFormatter, build_resource

_PACKAGE = "ipm_organization_publisher"
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


def test_event_is_one_json_line_with_the_log_record_fields() -> None:
    payload = format_line(record("requested handled", extra={"smarkee.outcome": "accepted"}))
    assert payload["body"] == "requested handled"
    assert payload["severity_number"] == 9
    assert payload["severity_text"] == "INFO"
    assert payload["scope"] == {"name": f"{_PACKAGE}.test"}
    assert payload["attributes"] == {"smarkee.outcome": "accepted"}
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
    assert "attributes" not in payload


def test_event_name_is_a_field_and_none_values_are_omitted() -> None:
    payload = format_line(
        record("x", extra={EVENT_NAME_KEY: "smarkee.message.rejected", "smarkee.reason": None})
    )
    assert payload["event_name"] == "smarkee.message.rejected"
    assert "attributes" not in payload


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
