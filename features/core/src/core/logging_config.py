"""Logs estruturados em JSON, uma linha por evento (`docs/RESOURCE-CONTROL-SECURITY.md` §13).

As chaves de contexto vêm do argumento `extra` dos loggers e são em inglês (`AGENTS.md` §16.1).
Mensagens de exceção **não** entram no log: elas podem conter valores de colunas (por exemplo, o
detalhe de uma violação de unicidade traz o e-mail), então só o tipo e o local são registrados.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_STANDARD_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRIBUTES:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
            traceback = record.exc_info[2]
            while traceback is not None and traceback.tb_next is not None:
                traceback = traceback.tb_next
            if traceback is not None:
                payload["error_location"] = (
                    f"{traceback.tb_frame.f_code.co_filename}:{traceback.tb_lineno}"
                )
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
