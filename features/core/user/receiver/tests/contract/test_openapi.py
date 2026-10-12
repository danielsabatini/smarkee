"""O OpenAPI versionado descreve a aplicação (artefato neutro, `docs/SCHEMA.md` §22)."""

import json
from pathlib import Path

from core_user_receiver.http.openapi import build_document

OPENAPI_FILE = Path(__file__).resolve().parents[2] / "openapi.json"


def test_versioned_openapi_matches_the_application() -> None:
    versioned = json.loads(OPENAPI_FILE.read_text("utf-8"))
    assert versioned == json.loads(json.dumps(build_document(), sort_keys=True)), (
        "openapi.json difere da aplicação: regere com `python -m core_user_receiver.http.openapi`"
    )


def test_every_route_is_under_the_user_resource() -> None:
    paths = json.loads(OPENAPI_FILE.read_text("utf-8"))["paths"]
    assert {path for path in paths if not path.startswith("/health/")} == {
        "/v1/users",
        "/v1/users/{user_id}",
        "/v1/users/{user_id}/operations/{operation_id}",
    }
