"""Modelos gerados a partir de schemas/ (decisão 0012; SCHEMA.md, Artefatos derivados)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from ipm_organization_receiver.contracts import generated

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_ROOT = PROJECT_ROOT.parents[3] / "schemas"
GENERATED_MODULE = PROJECT_ROOT / "src" / "ipm_organization_receiver" / "contracts" / "generated.py"
INDEX = SCHEMAS_ROOT / "ipm.organization.index.json"

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
    "ipm/organization/desired.example.json": generated.OrganizationDesiredData,
    "ipm/organization/observed.example.json": generated.OrganizationObservedData,
    "ipm/organization/requested-create.example.json": generated.OrganizationRequestedCreateData,
    "ipm/organization/requested-update.example.json": generated.OrganizationRequestedUpdateData,
    "ipm/organization/requested-delete.example.json": generated.OrganizationRequestedDeleteData,
    "ipm/organization/api-create-request.example.json": generated.OrganizationCreateRequest,
    "ipm/organization/api-update-request.example.json": generated.OrganizationUpdateRequest,
    "ipm/organization/resource.example.json": generated.Organization,
    "ipm/organization/resource-list.example.json": generated.OrganizationList,
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
    listed = {entry["$ref"] for entry in index["anyOf"]}
    contracts = {
        str(path.relative_to(SCHEMAS_ROOT))
        for directory in ("common", "ipm/organization")
        for path in (SCHEMAS_ROOT / directory).rglob("*.v*.schema.json")
        if not path.name.startswith("definitions.")
    }
    assert listed == contracts


def test_every_example_has_a_model() -> None:
    examples = {
        str(path.relative_to(SCHEMAS_ROOT))
        for directory in ("common", "ipm/organization")
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


def test_create_request_rejects_server_assigned_fields() -> None:
    for server_field in ("resourceId", "ownerAccountId", "requestedBy"):
        with pytest.raises(ValidationError):
            generated.OrganizationCreateRequest.model_validate(
                {**_example("ipm/organization/api-create-request.example.json"), server_field: "x"}
            )


def test_python_attributes_are_snake_case_and_json_is_camel_case() -> None:
    condition = generated.Condition.model_validate(_example("common/condition.example.json"))
    assert condition.observed_generation == 1
    dumped = condition.model_dump(mode="json", exclude_none=True)
    assert "observedGeneration" in dumped
    assert "observed_generation" not in dumped
    assert json.loads(condition.model_dump_json(exclude_none=True)) == dumped


def test_snake_case_input_is_rejected() -> None:
    example = _example("common/condition.example.json")
    snake_case_input = {
        "type": example["type"],
        "status": example["status"],
        "reason": example["reason"],
        "observed_generation": 1,
        "last_transition_at": example["lastTransitionAt"],
    }
    with pytest.raises(ValidationError):
        generated.Condition.model_validate(snake_case_input)


@pytest.mark.parametrize(
    ("relative_path", "model"), EXAMPLE_MODELS.items(), ids=list(EXAMPLE_MODELS)
)
def test_model_round_trips_the_example(relative_path: str, model: type[BaseModel]) -> None:
    example = _example(relative_path)
    assert model.model_validate(example).model_dump(mode="json", exclude_none=True) == example
