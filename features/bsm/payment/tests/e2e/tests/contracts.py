"""Validação contra os JSON Schemas de `schemas/` (só arquivos locais, sem referência remota)."""

import json
from functools import cache
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

SCHEMAS_ROOT = Path(__file__).resolve().parents[6] / "schemas"


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _refuse_remote(uri: str) -> Resource[Any]:
    raise NoSuchResource(ref=uri)


@cache
def _registry() -> Registry[Any]:
    files = sorted(SCHEMAS_ROOT.rglob("*.schema.json"))
    return Registry(retrieve=_refuse_remote).with_resources(  # pyright: ignore[reportCallIssue]
        (path.as_uri(), Resource.from_contents(_load(path))) for path in files
    )


def assert_valid(schema_file: str, instance: Any) -> None:
    """Falha se `instance` não respeita o schema (caminho relativo a `schemas/`)."""
    path = SCHEMAS_ROOT / schema_file
    validator = Draft202012Validator(
        {**_load(path), "$id": path.as_uri()},
        registry=_registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(instance)  # pyright: ignore[reportUnknownMemberType]
