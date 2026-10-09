"""Verificações dos contratos em schemas/ (SCHEMA.md, Verificações da pipeline e Testes).

Cobre common/ e o módulo core. As referências são resolvidas somente a partir dos arquivos
locais: qualquer tentativa de buscar uma URI fora de schemas/ falha.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

SCHEMAS_ROOT = Path(__file__).resolve().parents[4] / "schemas"
COVERED_DIRECTORIES = ("common", "core")
SCHEMA_FILE_PATTERN = re.compile(r"^(?P<contract>[a-z0-9-]+)\.v(?P<major>[0-9]+)\.schema\.json$")
SENSITIVITY_CLASSES = {"public", "internal", "confidential", "secretReference"}
WRITERS = {"client", "server"}
RESOURCE_PARAMETERS = {
    "observationInterval",
    "observationValidity",
    "actionDeadline",
    "failureLimit",
}
# Formatos cujo próprio padrão limita o tamanho: os modelos os convertem em datetime e timedelta,
# aos quais maxLength não se aplica.
LENGTH_BOUNDED_FORMATS = {"date-time", "duration"}


def _schema_files() -> list[Path]:
    return sorted(
        path
        for directory in COVERED_DIRECTORIES
        for path in (SCHEMAS_ROOT / directory).rglob("*.schema.json")
    )


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _refuse_remote(uri: str) -> Resource[Any]:
    raise NoSuchResource(ref=uri)


REGISTRY: Registry[Any] = Registry(retrieve=_refuse_remote).with_resources(  # pyright: ignore[reportCallIssue]
    (path.as_uri(), Resource.from_contents(_load(path))) for path in _schema_files()
)


def _validator(path: Path) -> Draft202012Validator:
    schema = _load(path)
    schema_with_base = {**schema, "$id": path.as_uri()}
    return Draft202012Validator(
        schema_with_base,
        registry=REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


# A tipagem de is_valid e validate no jsonschema tem sobrecarga com tipo desconhecido; as
# supressões ficam só aqui.
def _is_valid(path: Path, instance: Any) -> bool:  # instance: documento JSON arbitrário
    return _validator(path).is_valid(instance)  # pyright: ignore[reportUnknownMemberType]


def _validate(path: Path, instance: Any) -> None:  # instance: documento JSON arbitrário
    _validator(path).validate(instance)  # pyright: ignore[reportUnknownMemberType]


def _example_for(schema_path: Path) -> Path:
    match = SCHEMA_FILE_PATTERN.match(schema_path.name)
    assert match is not None
    return schema_path.with_name(f"{match['contract']}.example.json")


def _walk(node: object, location: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Percorre todos os subschemas (objetos JSON) com o caminho de cada um."""
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        yield location, mapping
        for key, value in mapping.items():
            yield from _walk(value, f"{location}/{key}")
    elif isinstance(node, list):
        for index, item in enumerate(cast(list[Any], node)):
            yield from _walk(item, f"{location}/{index}")


SCHEMA_FILES = _schema_files()
SCHEMA_IDS = [str(path.relative_to(SCHEMAS_ROOT)) for path in SCHEMA_FILES]
DEFINITION_FILES = {"definitions"}


CONDITIONAL_KEYWORDS = {"if", "then", "else"}


def _inside_conditional(location: str) -> bool:
    """Subschemas de if/then/else só restringem campos já declarados; não os redefinem."""
    return not CONDITIONAL_KEYWORDS.isdisjoint(location.split("/"))


def _is_definitions_file(path: Path) -> bool:
    match = SCHEMA_FILE_PATTERN.match(path.name)
    return match is not None and match["contract"] in DEFINITION_FILES


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_schema_is_valid_json_schema_2020_12(path: Path) -> None:
    schema = _load(path)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_file_name_and_declared_version_agree(path: Path) -> None:
    match = SCHEMA_FILE_PATTERN.match(path.name)
    assert match is not None, f"nome fora do padrão <contrato>.v<MAJOR>.schema.json: {path.name}"
    declared_version = _load(path)["x-schemaVersion"]
    assert re.fullmatch(r"[0-9]+\.[0-9]+", declared_version)
    assert declared_version.split(".")[0] == match["major"]


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_references_are_local_and_resolvable(path: Path) -> None:
    resolver = REGISTRY.resolver(base_uri=path.as_uri())
    for location, node in _walk(_load(path), "#"):
        reference = node.get("$ref")
        if isinstance(reference, str):
            assert not reference.startswith(("http:", "https:")), f"referência remota em {location}"
            resolver.lookup(reference)


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_every_string_and_array_has_limits(path: Path) -> None:
    for location, node in _walk(_load(path), "#"):
        bounded_by_format = node.get("format") in LENGTH_BOUNDED_FORMATS
        if (
            node.get("type") == "string"
            and not ({"enum", "const"} & node.keys())
            and not bounded_by_format
        ):
            assert "maxLength" in node, f"string sem maxLength em {location}"
        if node.get("type") == "array":
            assert "maxItems" in node, f"array sem maxItems em {location}"


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_objects_are_closed(path: Path) -> None:
    for location, node in _walk(_load(path), "#"):
        if node.get("type") != "object":
            continue
        # O data do envelope é aberto no envelope e fechado pelo contrato do messageType.
        if location.endswith("/properties/data"):
            assert "maxProperties" in node
            continue
        assert node.get("additionalProperties") is False, f"objeto aberto em {location}"


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_every_field_declares_sensitivity_and_writer(path: Path) -> None:
    for location, node in _walk(_load(path), "#"):
        properties = node.get("properties")
        if not isinstance(properties, dict) or location.endswith("/properties"):
            continue
        if _inside_conditional(location):
            continue
        for name, field in cast(dict[str, dict[str, Any]], properties).items():
            assert field.get("x-sensitivity") in SENSITIVITY_CLASSES, (
                f"{location}/properties/{name} sem x-sensitivity válida"
            )
            assert field.get("x-writer") in WRITERS, f"{location}/properties/{name} sem x-writer"


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=SCHEMA_IDS)
def test_every_enum_declares_policy(path: Path) -> None:
    for location, node in _walk(_load(path), "#"):
        if "enum" in node and not _inside_conditional(location):
            assert node.get("x-enumPolicy") in {"closed", "open"}, (
                f"enum sem x-enumPolicy em {location}"
            )


@pytest.mark.parametrize(
    "path", [path for path in SCHEMA_FILES if not _is_definitions_file(path)], ids=str
)
def test_example_exists_and_is_valid(path: Path) -> None:
    example_path = _example_for(path)
    assert example_path.exists(), f"exemplo ausente: {example_path.name}"
    _validate(path, json.loads(example_path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "path", [path for path in SCHEMA_FILES if not _is_definitions_file(path)], ids=str
)
def test_strict_mode_rejects_unknown_property(path: Path) -> None:
    example = json.loads(_example_for(path).read_text(encoding="utf-8"))
    example["unknownField"] = "x"
    assert not _is_valid(path, example)


ORGANIZATION = SCHEMAS_ROOT / "core" / "organization"


def test_desired_declares_all_resource_parameters() -> None:
    desired = _load(ORGANIZATION / "desired.v1.schema.json")
    assert set(desired["x-resourceParameters"]) == RESOURCE_PARAMETERS
    assert "x-actionIdFormat" in desired


@pytest.mark.parametrize(
    ("contract", "server_field"),
    [
        ("api-create-request", "resourceId"),
        ("api-create-request", "operationId"),
        ("api-create-request", "requestedBy"),
        ("api-create-request", "platformAccess"),
        ("api-update-request", "desiredGeneration"),
        ("api-update-request", "operationId"),
    ],
)
def test_client_request_rejects_server_assigned_fields(contract: str, server_field: str) -> None:
    schema_path = ORGANIZATION / f"{contract}.v1.schema.json"
    example = json.loads(_example_for(schema_path).read_text(encoding="utf-8"))
    example[server_field] = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
    assert not _is_valid(schema_path, example)


def test_resource_view_never_exposes_first_administrator() -> None:
    resource = _load(ORGANIZATION / "resource.v1.schema.json")
    assert "firstAdministrator" not in resource["properties"]["desired"]["properties"]


@pytest.mark.parametrize(
    "resource_id",
    ["Upper", "-leading", "trailing-", "has.dot", "has space", "a" * 129, ""],
)
def test_resource_id_pattern_rejects_invalid_values(resource_id: str) -> None:
    accepted_response = SCHEMAS_ROOT / "common" / "api-accepted-response.v1.schema.json"
    assert not _is_valid(accepted_response, {"resourceId": resource_id, "operationId": "op-1"})


def test_envelope_requires_type_specific_fields() -> None:
    envelope_path = SCHEMAS_ROOT / "common" / "message-envelope.v1.schema.json"
    message = cast(
        dict[str, Any], json.loads(_example_for(envelope_path).read_text(encoding="utf-8"))
    )
    del message["desiredGeneration"]
    assert not _is_valid(envelope_path, message)

    observed: dict[str, Any] = {
        **message,
        "messageType": "observed",
        "emitter": "observer",
        "data": {},
    }
    assert not _is_valid(envelope_path, observed)
    observed |= {"presence": "present", "observedAt": "2026-10-09T14:00:02Z"}
    assert _is_valid(envelope_path, observed)


def test_update_request_requires_a_change() -> None:
    update_path = ORGANIZATION / "api-update-request.v1.schema.json"
    assert not _is_valid(update_path, {"resourceVersion": "3"})
    requested_update = ORGANIZATION / "requested-update.v1.schema.json"
    assert not _is_valid(
        requested_update, {"operationId": "op-1", "requestDigest": "0" * 64, "resourceVersion": "3"}
    )


def test_rejected_operation_requires_reason_and_no_generation() -> None:
    operation_path = SCHEMAS_ROOT / "common" / "operation.v1.schema.json"
    operation = json.loads(_example_for(operation_path).read_text(encoding="utf-8"))
    rejected = {**operation, "operationStatus": "rejected"}
    assert not _is_valid(operation_path, rejected)
    del rejected["desiredGeneration"]
    rejected["operationStatusReason"] = "conflict"
    assert _is_valid(operation_path, rejected)
    assert not _is_valid(operation_path, {**operation, "operationStatusReason": "conflict"})
