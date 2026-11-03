"""O OpenAPI versionado descreve a aplicação (artefato neutro, `docs/data/SCHEMA.md` §22)."""

import json
from pathlib import Path

from cam_account.api.http.openapi import build_document

OPENAPI_FILE = Path(__file__).resolve().parents[3] / "openapi.json"


def test_versioned_openapi_matches_the_application() -> None:
    versioned = json.loads(OPENAPI_FILE.read_text("utf-8"))
    assert versioned == json.loads(json.dumps(build_document(), sort_keys=True)), (
        "openapi.json difere da aplicação: regere com `python -m cam_account.api.http.openapi`"
    )


def test_every_route_is_under_the_account_resource() -> None:
    paths = json.loads(OPENAPI_FILE.read_text("utf-8"))["paths"]
    assert {path for path in paths if not path.startswith("/health/")} == {
        "/v1/cam/accounts",
        "/v1/cam/accounts/{account_id}",
        "/v1/cam/accounts/registration-status/{ticket}",
        "/v1/cam/accounts/registration-status/{ticket}/resend",
    }
