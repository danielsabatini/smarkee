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

# Contratos comuns que esta feature não usa depois da API síncrona (decisão 0098): a Operation e a
# resposta `202` com `operationId` ficam para as features que ainda têm Receiver e Manager.
UNUSED_COMMON = {"operation", "api-accepted-response"}

EXAMPLE_MODELS: dict[str, type[BaseModel]] = {
    "common/message-envelope.example.json": generated.MessageEnvelope,
    "common/condition.example.json": generated.Condition,
    "common/action.example.json": generated.ActionData,
    "common/completed.example.json": generated.CompletedData,
    "common/failed.example.json": generated.FailedData,
    "common/updated.example.json": generated.UpdatedData,
    "common/api-error.example.json": generated.ApiError,
    "ipm/role/desired.example.json": generated.RoleDesiredData,
    "ipm/role/observed.example.json": generated.RoleObservedData,
    "ipm/role/api-create-request.example.json": generated.RoleCreateRequest,
    "ipm/role/api-update-request.example.json": generated.RoleUpdateRequest,
    "ipm/role/resource.example.json": generated.Role,
    "ipm/role/resource-list.example.json": generated.RoleList,
}


def _example(relative_path: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((SCHEMAS_ROOT / relative_path).read_text("utf-8")))


def test_generated_models_match_regeneration() -> None:
    # Dentro do projeto, para o formatador usar a mesma configuração (line-length) do arquivo
    # versionado; o diretório temporário é removido ao final.
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
    # Fragmentos (`#/$defs/...`) trazem definições usadas pelo código e sem contrato que as
    # referencie, como o catálogo `grantablePermission` (decisão 0081); não contam como contrato.
    listed = {entry["$ref"] for entry in index["anyOf"] if "#" not in entry["$ref"]}
    contracts = {
        str(path.relative_to(SCHEMAS_ROOT))
        for directory in ("common", "ipm/role")
        for path in (SCHEMAS_ROOT / directory).rglob("*.v*.schema.json")
        if not path.name.startswith("definitions.") and path.name.split(".")[0] not in UNUSED_COMMON
    }
    assert listed == contracts


def test_every_example_has_a_model() -> None:
    examples = {
        str(path.relative_to(SCHEMAS_ROOT))
        for directory in ("common", "ipm/role")
        for path in (SCHEMAS_ROOT / directory).rglob("*.example.json")
        if path.name.split(".")[0] not in UNUSED_COMMON
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


def test_create_request_rejects_server_assigned_fields() -> None:
    for server_field in ("resourceId", "requestedBy"):
        with pytest.raises(ValidationError):
            generated.RoleCreateRequest.model_validate(
                {**_example("ipm/role/api-create-request.example.json"), server_field: "x"}
            )
