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
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast

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

# Contexto da requisição ou da mensagem em tratamento (decisões 0055 e 0061). Não há SDK de
# tracing: o componente repassa o `traceparent` recebido e grava nos logs o trace (`trace_id`,
# `trace_flags`) e o contexto de negócio (ator, recurso, ação, dono, organização), para o
# drill-down.
TRACEPARENT_HEADER = "traceparent"
_TRACEPARENT = re.compile(r"^00-(?!0{32}-)([0-9a-f]{32})-(?!0{16}-)[0-9a-f]{16}-([0-9a-f]{2})\Z")
# Só identificadores opacos: o formato não admite `@` nem `.`, então um e-mail nunca passa.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}\Z")
_OPERATION = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")
ANONYMOUS_ACTOR = "anonymous"
ACTOR_TYPES = ("user", "anonymous", "service", "system")
# Recursos cujo `resourceId` é o identificador de uma Organization.
_ORGANIZATION_RESOURCES = frozenset({("ipm", "organization")})


@dataclass(frozen=True, slots=True)
class _Context:
    traceparent: str | None = None
    actor_id: str | None = None
    actor_type: str | None = None
    resource_id: str | None = None
    operation: str | None = None
    owner_id: str | None = None
    organization_id: str | None = None


_EMPTY = _Context()
_context: ContextVar[_Context | None] = ContextVar("log_context", default=None)


def _current() -> _Context:
    return _context.get() or _EMPTY


def bind_traceparent(value: str | None) -> str | None:
    """Inicia um contexto novo com o `traceparent`, se válido (W3C versão 00); senão, vazio.

    Descarta o contexto de negócio anterior: é o que o `finally` dos consumidores usa para limpar
    (`bind_traceparent(None)`). Devolve o valor associado ou `None`; um valor inválido nunca é
    repassado nem registrado.
    """
    valid = value if value is not None and _TRACEPARENT.match(value) else None
    _context.set(_Context(traceparent=valid))
    return valid


def save_context() -> object:
    """Captura o contexto atual, para quem precisa trocá-lo por um tempo e depois restaurá-lo."""
    return _current()


def restore_context(saved: object) -> None:
    """Restaura um contexto capturado por `save_context` (o argumento não é inspecionado)."""
    _context.set(saved if isinstance(saved, _Context) else None)


def current_traceparent() -> str | None:
    """`traceparent` associado ao contexto atual (para repassar em mensagens), ou `None`."""
    return _current().traceparent


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.match(value) else None


def bind_context(
    *,
    requested_by: str | None = None,
    resource_id: str | None = None,
    operation: str | None = None,
    owner_id: str | None = None,
    organization_id: str | None = None,
    actor_type: str | None = None,
) -> None:
    """Acrescenta ao contexto atual o ator, o recurso, a ação, o dono e a organização.

    `requested_by` é o solicitante: `anonymous` (escrita anônima) vira o tipo de ator `anonymous`,
    sem id; um identificador opaco vira `user`. Valor que não seja identificador opaco (por exemplo,
    um e-mail) é descartado, nunca registrado. `actor_type` só vale quando não há ator (por exemplo,
    `system`).
    Campo ausente ou inválido mantém o que já estava no contexto.
    """
    current = _current()
    actor_id, kind = current.actor_id, current.actor_type
    if requested_by == ANONYMOUS_ACTOR:
        actor_id, kind = None, "anonymous"
    elif _identifier(requested_by) is not None:
        actor_id, kind = requested_by, "user"
    elif actor_type in ACTOR_TYPES and kind is None:
        kind = actor_type
    _context.set(
        replace(
            current,
            actor_id=actor_id,
            actor_type=kind,
            resource_id=_identifier(resource_id) or current.resource_id,
            operation=(
                operation if isinstance(operation, str) and _OPERATION.match(operation) else None
            )
            or current.operation,
            owner_id=_identifier(owner_id) or current.owner_id,
            organization_id=_identifier(organization_id) or current.organization_id,
        )
    )


def bind_message_context(message: bytes | str | Mapping[str, Any]) -> None:
    """Preenche o contexto a partir de um envelope de mensagem (`docs/MESSAGING.md`).

    Lê `requestedBy`, `resourceId`, `operation`, `data.ownerAccountId` e, para Organization, o
    `resourceId` como organização. Mensagem sem solicitante registrado (as `observed` do Observer,
    os fatos `updated`) é do tipo `system`: origem na plataforma, e não numa requisição.
    Mensagem ilegível é ignorada: o contexto é auxílio de diagnóstico, nunca motivo de falha.
    """
    parsed: object = message
    if isinstance(message, bytes | str):
        try:
            parsed = json.loads(message)
        except ValueError:
            return
    if not isinstance(parsed, Mapping):
        return
    envelope = cast("Mapping[str, Any]", parsed)
    data = envelope.get("data")
    owner = (
        cast("Mapping[str, Any]", data).get("ownerAccountId") if isinstance(data, Mapping) else None
    )
    resource_id = envelope.get("resourceId")
    is_organization = (
        envelope.get("module"),
        envelope.get("resourceType"),
    ) in _ORGANIZATION_RESOURCES
    requested_by = envelope.get("requestedBy")
    bind_context(
        requested_by=requested_by if isinstance(requested_by, str) else None,
        resource_id=resource_id if isinstance(resource_id, str) else None,
        operation=envelope.get("operation") if isinstance(envelope.get("operation"), str) else None,
        owner_id=owner if isinstance(owner, str) else None,
        organization_id=resource_id if is_organization and isinstance(resource_id, str) else None,
        actor_type="system",
    )


def _context_attributes(role: str | None) -> dict[str, str]:
    """Atributos de log vindos do contexto atual. O Observer é sempre `system`, sem solicitante."""
    context = _current()
    found: dict[str, str] = {}
    if context.actor_id is not None:
        found["user.id"] = context.actor_id
    kind = context.actor_type or ("system" if role == "observer" else None)
    if kind is not None:
        found["smarkee.actor.type"] = kind
    for key, value in (
        ("smarkee.resource.id", context.resource_id),
        ("smarkee.operation.name", context.operation),
        ("smarkee.owner.id", context.owner_id),
        ("smarkee.organization.id", context.organization_id),
    ):
        if value is not None:
            found[key] = value
    return found


def build_resource(role: str) -> dict[str, str]:
    """Atributos de `Resource` do componente, fixos durante o processo (`OBSERVABILITY.md` §4).

    O pacote nomeia a feature (`<módulo>_<tipo>`, decisão 0063) e o papel é informado por quem
    chama (o entrypoint de cada papel).
    """
    package_parts = __name__.partition(".")[0].split("_")
    if len(package_parts) != 2:
        raise ValueError(f"package name must be <module>_<type>: {'_'.join(package_parts)}")
    module, resource_type = package_parts
    resource = {
        "service.name": f"{module}-{resource_type}-{role}",
        "service.namespace": "smarkee",
        "service.instance.id": str(uuid.uuid4()),
        "smarkee.module": module,
        "smarkee.resource.type": resource_type,
        "smarkee.component.role": role,
    }
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        resource["service.version"] = importlib.metadata.version("-".join(package_parts))
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
        # O que o evento informa explicitamente prevalece sobre o contexto.
        for key, value in _context_attributes(self._resource.get("smarkee.component.role")).items():
            attributes.setdefault(key, value)
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
        traceparent = _current().traceparent
        if traceparent is not None:
            payload["trace_id"] = traceparent[3:35]
            payload["trace_flags"] = int(traceparent[-2:], 16)
        payload["resource"] = self._resource
        if attributes:
            payload["attributes"] = attributes
        return json.dumps(payload, default=str, ensure_ascii=False)


DEPENDENCY_LOGGERS = ("httpx", "httpcore", "uvicorn", "nats", "psycopg", "asyncio")
"""Loggers das bibliotecas: têm nível próprio (`log.dependencies_level`)."""


def configure_logging(
    role: str, level: int | str = logging.INFO, dependencies_level: int | str = logging.WARNING
) -> None:
    """Saída JSON em `stdout` no nível do papel; as bibliotecas ficam no nível delas.

    Pode ser chamada de novo: na partida, antes de ler a configuração (para registrar uma
    configuração inválida), e depois, com o nível configurado.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(build_resource(role)))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in DEPENDENCY_LOGGERS:
        logging.getLogger(name).setLevel(dependencies_level)
