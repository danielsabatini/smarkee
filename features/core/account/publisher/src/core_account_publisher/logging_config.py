"""Logs como LogRecord do OpenTelemetry: uma linha JSON por evento no stdout (decisão 0045).

O formato, os campos e as proibições estão em `docs/OBSERVABILITY.md`. As chaves de contexto vêm
do argumento `extra` dos loggers e são nomes de atributo da semconv ou `smarkee.*`, em inglês
(`AGENTS.md` §16.1). A mensagem e a pilha de uma exceção **não** entram no log: elas podem conter
valores de colunas (por exemplo, o detalhe de uma violação de unicidade traz o e-mail), então só o
tipo e o local são registrados.

Este arquivo é idêntico em todos os componentes (decisão 0015); a identidade do componente vem do
nome do pacote, `<módulo>_<tipo>_<papel>`.
"""

import contextlib
import importlib.metadata
import json
import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

_ENVIRONMENT_VARIABLE = "SMARKEE_ENVIRONMENT"
_ENVIRONMENT_NAMES = {"dev": "development", "stg": "staging", "prd": "production"}

# Do maior nível do Python para o menor: (nível, SeverityNumber, SeverityText).
_SEVERITIES = (
    (logging.CRITICAL, 21, "FATAL"),
    (logging.ERROR, 17, "ERROR"),
    (logging.WARNING, 13, "WARN"),
    (logging.INFO, 9, "INFO"),
    (logging.DEBUG, 5, "DEBUG"),
)
_TRACE_SEVERITY = (1, "TRACE")

_STANDARD_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    # O uvicorn acrescenta a mensagem colorida do terminal a alguns registros; não é atributo.
    "color_message",
}

# Chave de `extra` que vira o campo `EventName` do LogRecord, e não um atributo.
EVENT_NAME_KEY = "event_name"

# Contexto de trace W3C (`traceparent`) da requisição ou da mensagem em tratamento. Não há SDK de
# tracing: o componente só repassa o contexto recebido e o grava nos logs (`trace_id` e
# `trace_flags`).
TRACEPARENT_HEADER = "traceparent"
_TRACEPARENT = re.compile(r"^00-(?!0{32}-)([0-9a-f]{32})-(?!0{16}-)[0-9a-f]{16}-([0-9a-f]{2})\Z")
_current_traceparent: ContextVar[str | None] = ContextVar("traceparent", default=None)


def bind_traceparent(value: str | None) -> str | None:
    """Associa o `traceparent` ao contexto atual, se for válido (W3C versão 00); senão, limpa.

    Devolve o valor associado ou `None`. Um valor inválido nunca é repassado nem registrado.
    """
    valid = value if value is not None and _TRACEPARENT.match(value) else None
    _current_traceparent.set(valid)
    return valid


def current_traceparent() -> str | None:
    """`traceparent` associado ao contexto atual (para repassar em mensagens), ou `None`."""
    return _current_traceparent.get()


def build_resource() -> dict[str, str]:
    """Atributos de `Resource` do componente, fixos durante o processo (`OBSERVABILITY.md` §4)."""
    package = __name__.partition(".")[0]
    parts = package.split("_")
    if len(parts) != 3:
        raise ValueError(f"package name must be <module>_<type>_<role>: {package}")
    module, resource_type, role = parts
    resource = {
        "service.name": "-".join(parts),
        "service.namespace": "smarkee",
        "service.instance.id": str(uuid.uuid4()),
        "smarkee.module": module,
        "smarkee.resource.type": resource_type,
        "smarkee.component.role": role,
    }
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        resource["service.version"] = importlib.metadata.version("-".join(parts))
    environment = _ENVIRONMENT_NAMES.get(os.environ.get(_ENVIRONMENT_VARIABLE, ""))
    if environment is not None:
        resource["deployment.environment.name"] = environment
    return resource


def _severity(level: int) -> tuple[int, str]:
    for threshold, number, text in _SEVERITIES:
        if level >= threshold:
            return number, text
    return _TRACE_SEVERITY


def _qualified_name(error_class: type[BaseException]) -> str:
    if error_class.__module__ == "builtins":
        return error_class.__qualname__
    return f"{error_class.__module__}.{error_class.__qualname__}"


def _error_attributes(
    error_class: type[BaseException], traceback: TracebackType | None
) -> dict[str, Any]:
    """`error.type`, `exception.type` e o local do último quadro; nunca a mensagem nem a pilha."""
    error_type = _qualified_name(error_class)
    attributes: dict[str, Any] = {"error.type": error_type, "exception.type": error_type}
    while traceback is not None and traceback.tb_next is not None:
        traceback = traceback.tb_next
    if traceback is not None:
        code = traceback.tb_frame.f_code
        module = traceback.tb_frame.f_globals.get("__name__", "")
        attributes["code.file.path"] = code.co_filename
        attributes["code.line.number"] = traceback.tb_lineno
        attributes["code.function.name"] = f"{module}.{code.co_qualname}"
    return attributes


class JsonFormatter(logging.Formatter):
    def __init__(self, resource: dict[str, str]) -> None:
        super().__init__()
        self._resource = resource

    def format(self, record: logging.LogRecord) -> str:
        severity_number, severity_text = _severity(record.levelno)
        attributes: dict[str, Any] = {}
        event_name: str | None = None
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRIBUTES or value is None:
                continue
            if key == EVENT_NAME_KEY:
                event_name = str(value)
            else:
                attributes[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            attributes.update(_error_attributes(record.exc_info[0], record.exc_info[2]))
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "severity_number": severity_number,
            "severity_text": severity_text,
            "body": record.getMessage(),
        }
        if event_name is not None:
            payload["event_name"] = event_name
        payload["scope"] = {"name": record.name}
        traceparent = _current_traceparent.get()
        if traceparent is not None:
            payload["trace_id"] = traceparent[3:35]
            payload["trace_flags"] = int(traceparent[-2:], 16)
        payload["resource"] = self._resource
        if attributes:
            payload["attributes"] = attributes
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(build_resource()))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
