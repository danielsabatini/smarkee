"""O enum `grantablePermission` é a semente do catálogo e deve acompanhar a semente do banco.

O catálogo vivo vem de `grantable = true` em `ipm.permission` (decisão 0083); o enum de
`schemas/ipm/definitions.v1.schema.json` só vale até o replay do NATS. Se os dois divergirem, um
Receiver recém-iniciado aceita ou recusa permissões de forma diferente da plataforma.
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = PROJECT_ROOT.parents[2] / "schemas" / "ipm" / "definitions.v1.schema.json"
SEED = PROJECT_ROOT / "migrations" / "0001-permission.sql"

# ('<uuid>', '<nome>', '<módulo>', '<descrição>', <grantable>)
SEED_ROW = re.compile(
    r"\('[0-9a-f-]{36}',\s*'(?P<name>[a-z.]+)',\s*'(?P<module>\w+)',\s*'[^']*',\s*(?P<grantable>true|false)\)"
)


def test_the_seed_enum_lists_exactly_the_grantable_ipm_permissions_of_the_seed() -> None:
    seeded = {
        row["name"]
        for row in SEED_ROW.finditer(SEED.read_text(encoding="utf-8"))
        if row["module"] == "ipm" and row["grantable"] == "true"
    }
    enum = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]["grantablePermission"]["enum"]
    assert seeded, "a semente não foi lida: o padrão das linhas mudou"
    assert set(enum) == seeded
    assert enum == sorted(enum)
