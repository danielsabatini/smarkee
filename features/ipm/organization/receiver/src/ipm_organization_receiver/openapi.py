"""Gera o OpenAPI do Receiver (artefato neutro, versionado em `openapi.json`).

Uso: `python -m ipm_organization_receiver.openapi > openapi.json`. A aplicação não expõe o
documento por HTTP (`openapi_url=None`); o arquivo versionado é o contrato descritivo, e o teste
`tests/contract/test_openapi.py` falha se ele divergir do código (`docs/SCHEMA.md` §22).
"""

import json
import sys
from typing import Any, cast

from ipm_organization_receiver.app import Dependencies, create_app


def build_document() -> dict[str, Any]:
    # As dependências não são usadas para descrever as rotas.
    app = create_app(cast("Dependencies", None))
    return app.openapi()


def main() -> None:
    json.dump(build_document(), sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
