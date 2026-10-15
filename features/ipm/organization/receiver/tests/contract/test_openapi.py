"""O OpenAPI versionado descreve a aplicação (artefato neutro, `docs/SCHEMA.md` §22)."""

import json
from pathlib import Path

from ipm_organization_receiver.openapi import build_document

OPENAPI_FILE = Path(__file__).resolve().parents[2] / "openapi.json"


def test_versioned_openapi_matches_the_application() -> None:
    versioned = json.loads(OPENAPI_FILE.read_text("utf-8"))
    assert versioned == json.loads(json.dumps(build_document(), sort_keys=True)), (
        "openapi.json difere da aplicação: regere com `python -m ipm_organization_receiver.openapi`"
    )


def test_every_route_is_under_the_organization_resource() -> None:
    paths = json.loads(OPENAPI_FILE.read_text("utf-8"))["paths"]
    assert {path for path in paths if path != "/healthz"} == {
        "/v1/ipm/organizations",
        "/v1/ipm/organizations/{organization_id}",
        "/v1/ipm/organizations/{organization_id}/operations/{operation_id}",
    }
