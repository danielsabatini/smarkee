"""Modelos gerados a partir de schemas/ (decisão 0012; SCHEMA.md, Artefatos derivados)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from ipm_role.common.contracts import generated

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_ROOT = PROJECT_ROOT.parents[2] / "schemas"
GENERATED_MODULE = PROJECT_ROOT / "src" / "ipm_role" / "common" / "contracts" / "generated.py"
INDEX = SCHEMAS_ROOT / "ipm.role.index.json"

EXAMPLE_MODELS: dict[str, type[BaseModel]] = {
    "common/message-envelope.example.json": generated.MessageEnvelope,
    "common/condition.example.json": generated.Condition,
    "common/action.example.json": generated.ActionData,
    "common/completed.example.json": generated.CompletedData,
    "common/failed.example.json": generated.FailedData,
    "common/updated.example.json": generated.UpdatedData,
    "common/operation.example.json": generated.Operation,
    "common/api-accepted-response.example.json": generated.ApiAcceptedResponse,
    "common/api-error.example.json": generated.ApiError,
    "ipm/role/desired.example.json": generated.RoleDesiredData,
    "ipm/role/observed.example.json": generated.RoleObservedData,
    "ipm/role/requested-create.example.json": generated.RoleRequestedCreateData,
    "ipm/role/requested-update.example.json": generated.RoleRequestedUpdateData,
    "ipm/role/requested-delete.example.json": generated.RoleRequestedDeleteData,
    "ipm/role/api-create-request.example.json": generated.RoleCreateRequest,
    "ipm/role/api-update-request.example.json": generated.RoleUpdateRequest,
    "ipm/role/resource.example.json": generated.Role,
    "ipm/role/resource-list.example.json": generated.RoleList,
}


def _example(relative_path: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((SCHEMAS_ROOT / relative_path).read_text("utf-8")))


def test_generated_models_match_regeneration() -> None:
    with tempfile.TemporaryDirectory(prefix=".codegen-check-", dir=PROJECT_ROOT) as directory:
        regenerated = Path(directory) / "generated.py"
        subprocess.run(  # noqa: S603 (comando fixo, sem entrada externa)
            [sys.executable, "-m", "datamodel_code_generator", "--output", str(regenerated)],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
        regenerated_content = regenerated.read_text("utf-8")
    assert regenerated_content == GENERATED_MODULE.read_text("utf-8"), (
        "contracts/generated.py difere da regeneração: rode `uv run datamodel-codegen`"
    )


def test_index_lists_every_contract() -> None:
    index = cast(dict[str, Any], json.loads(INDEX.read_text("utf-8")))
    listed = {entry["$ref"] for entry in index["anyOf"]}
    contracts = {
        str(path.relative_to(SCHEMAS_ROOT))
        for directory in ("common", "ipm/role")
        for path in (SCHEMAS_ROOT / directory).rglob("*.v*.schema.json")
        if not path.name.startswith("definitions.")
    }
    assert listed == contracts


def test_every_example_has_a_model() -> None:
    examples = {
        str(path.relative_to(SCHEMAS_ROOT))
        for directory in ("common", "ipm/role")
        for path in (SCHEMAS_ROOT / directory).rglob("*.example.json")
    }
    assert examples == set(EXAMPLE_MODELS)


@pytest.mark.parametrize(
    ("relative_path", "model"), EXAMPLE_MODELS.items(), ids=list(EXAMPLE_MODELS)
)
def test_model_accepts_example(relative_path: str, model: type[BaseModel]) -> None:
    model.model_validate(_example(relative_path))


@pytest.mark.parametrize(
    ("relative_path", "model"), EXAMPLE_MODELS.items(), ids=list(EXAMPLE_MODELS)
)
def test_model_rejects_unknown_field(relative_path: str, model: type[BaseModel]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**_example(relative_path), "unknownField": "x"})
