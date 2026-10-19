"""Verificações do contrato de log em schemas/observability (docs/OBSERVABILITY.md, decisão 0045).

Cobre o schema da linha de log e a igualdade das cópias do formatter nos componentes (decisão 0046).
"""

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

OBSERVABILITY = Path(__file__).resolve().parents[1] / "observability"
SCHEMA = cast(
    dict[str, Any],
    json.loads((OBSERVABILITY / "log-record.v1.schema.json").read_text(encoding="utf-8")),
)
EXAMPLE = cast(
    dict[str, Any],
    json.loads((OBSERVABILITY / "log-record.example.json").read_text(encoding="utf-8")),
)
VALIDATOR = Draft202012Validator(SCHEMA)


def _is_valid(line: dict[str, Any]) -> bool:
    return VALIDATOR.is_valid(line)  # pyright: ignore[reportUnknownMemberType]


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        found.append(mapping)
        for value in mapping.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for item in cast(list[Any], node):
            found.extend(_walk(item))
    return found


def _with(change: dict[str, Any]) -> dict[str, Any]:
    line = copy.deepcopy(EXAMPLE)
    line.update(change)
    return line


def _with_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    return _with({"attributes": attributes})


def test_schema_is_valid_json_schema_2020_12() -> None:
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(SCHEMA)


def test_example_is_valid() -> None:
    assert _is_valid(EXAMPLE)


def test_every_string_and_array_has_limits() -> None:
    for node in _walk(SCHEMA):
        bounded = {"enum", "const"} & node.keys()
        if node.get("type") == "string" and not bounded:
            assert "maxLength" in node, node
        if node.get("type") == "array":
            assert "maxItems" in node, node


def test_objects_with_known_fields_are_closed() -> None:
    for node in _walk(SCHEMA):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False, node


@pytest.mark.parametrize("forbidden", ["exception.message", "exception.stacktrace"])
def test_exception_message_and_stacktrace_are_forbidden(forbidden: str) -> None:
    assert not _is_valid(_with_attributes({"exception.type": "ValueError", forbidden: "x"}))


@pytest.mark.parametrize("name", ["foo", "error_type", "resource_id", "smarkee", "Smarkee.x"])
def test_attribute_outside_the_semconv_list_and_the_smarkee_namespace_is_rejected(
    name: str,
) -> None:
    assert not _is_valid(_with_attributes({name: "x"}))


def test_smarkee_namespace_accepts_scalars_and_lists_but_not_null() -> None:
    assert _is_valid(_with_attributes({"smarkee.outcome": "accepted", "smarkee.count": 3}))
    assert _is_valid(_with_attributes({"smarkee.config.missing_variables": ["A", "B"]}))
    assert not _is_valid(_with_attributes({"smarkee.outcome": None}))
    assert not _is_valid(_with_attributes({"smarkee.outcome": {"nested": "x"}}))


@pytest.mark.parametrize(
    ("number", "text", "valid"),
    [(9, "INFO", True), (17, "ERROR", True), (17, "INFO", False), (3, "INFO", False)],
)
def test_severity_text_must_match_severity_number(number: int, text: str, valid: bool) -> None:
    assert _is_valid(_with({"severity_number": number, "severity_text": text})) is valid


def test_span_id_requires_trace_id() -> None:
    span_only = _with({"span_id": "0123456789abcdef"})
    assert not _is_valid(span_only)
    assert _is_valid({**span_only, "trace_id": "0123456789abcdef0123456789abcdef"})


@pytest.mark.parametrize("event_name", ["smarkee.message.rejected", "smarkee.started"])
def test_event_name_follows_the_smarkee_pattern(event_name: str) -> None:
    assert _is_valid(_with({"event_name": event_name}))


@pytest.mark.parametrize("event_name", ["rejected", "Smarkee.Rejected", "smarkee.", "x.smarkee.y"])
def test_event_name_outside_the_pattern_is_rejected(event_name: str) -> None:
    assert not _is_valid(_with({"event_name": event_name}))


@pytest.mark.parametrize(
    "missing", ["timestamp", "severity_number", "severity_text", "body", "scope", "resource"]
)
def test_required_fields(missing: str) -> None:
    line = copy.deepcopy(EXAMPLE)
    del line[missing]
    assert not _is_valid(line)


@pytest.mark.parametrize(
    "missing",
    ["service.name", "service.namespace", "service.instance.id", "smarkee.module"],
)
def test_resource_identifies_the_component(missing: str) -> None:
    line = copy.deepcopy(EXAMPLE)
    del line["resource"][missing]
    assert not _is_valid(line)


def test_unknown_top_level_field_is_rejected() -> None:
    assert not _is_valid(_with({"message": "legacy key"}))
    assert not _is_valid(_with({"time": "2026-10-16T14:03:22.123456Z"}))
