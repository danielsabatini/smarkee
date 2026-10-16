"""API do Receiver de `sum.service` (decisão 0033).

- `POST /v1/sum/services`: liga um serviço para o solicitante (`202`, com `resourceId` e
`operationId`).
- `GET /v1/sum/services` e `GET /v1/sum/services/{resourceId}`: leem as ligações do solicitante.
- `DELETE /v1/sum/services/{resourceId}?resourceVersion=`: desliga (`202`).
- `GET /v1/sum/services/{resourceId}/operations/{operationId}`: acompanha a Operation.

O Receiver valida o token, confere a role da ação e a posse da ligação, e publica o `requested`. A
decisão
(catálogo, unicidade, versão) é do Manager. Repetir com a mesma `Idempotency-Key` devolve a operação
já
aceita; com outro corpo, `422`.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from sum_service_receiver.auth.tokens import TokenVerifier
from sum_service_receiver.contracts import generated
from sum_service_receiver.domain.dependents import DependentsCheckError
from sum_service_receiver.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
    unavailable,
    unprocessable,
)
from sum_service_receiver.domain.principal import (
    ACTION_DISABLE,
    ACTION_ENABLE,
    ACTION_GET,
    Principal,
    service_role,
)
from sum_service_receiver.domain.requests import (
    operation_id_for,
    request_digest,
    validate_resource_id,
    validate_service,
    validate_version,
)
from sum_service_receiver.http.health import Health
from sum_service_receiver.ids import new_identifier, utc_now

logger = logging.getLogger(__name__)

MODULE = "sum"
RESOURCE_TYPE = "service"
SCHEMA_VERSION = "1.0"
PUBLISHED_BY = "sum-service-receiver"
MAX_IDEMPOTENCY_KEY = 128
MAX_LIST_LIMIT = 200


class Repo(Protocol):
    async def link(self, resource_id: str) -> dict[str, Any] | None: ...
    async def links_of(self, owner_account_id: str) -> list[dict[str, Any]]: ...
    async def link_for_pair(
        self, owner_account_id: str, service: str
    ) -> tuple[str, str] | None: ...
    async def operation(self, operation_id: str) -> dict[str, Any] | None: ...
    async def operation_of(self, resource_id: str, operation_id: str) -> dict[str, Any] | None: ...


class Dependents(Protocol):
    async def count(self, service: str, access_token: str) -> int:
        """Recursos do dono do token que dependem do serviço, pelo fluxo normal do módulo dono.

        Levanta `DependentsCheckError` se o módulo não puder ser consultado.
        """
        ...


class Publish(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Dependencies:
    verifier: TokenVerifier
    repository: Repo
    publisher: Publish
    health: Health
    dependents: Dependents
    now: Callable[[], Any] = utc_now


_ERROR_DESCRIPTIONS = {
    400: "Entrada inválida (`ValidationFailed`).",
    401: "Token ausente ou inválido (`Unauthorized`).",
    403: "O solicitante não tem a role da ação (`Forbidden`).",
    404: "Recurso inexistente ou de outro dono (`NotFound`).",
    409: "Conflito: serviço já habilitado, ou versão desatualizada (`Conflict`).",
    422: "A chave de idempotência já foi usada com outro pedido (`IdempotencyKeyReused`).",
    503: "O pedido não pôde ser registrado agora; repita depois do `Retry-After`.",
}


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Respostas de erro documentadas de uma rota, todas no formato do contrato `ApiError`."""
    return {
        status: {"model": generated.ApiError, "description": _ERROR_DESCRIPTIONS[status]}
        for status in statuses
    }


def _install_openapi(app: FastAPI) -> None:
    """OpenAPI sem a resposta `422` padrão do FastAPI: aqui a entrada inválida é `400`, e o `422`
    é só o reuso da chave de idempotência (declarado nas rotas que a aceitam)."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            for operations in schema["paths"].values():
                for operation in operations.values():
                    default = operation["responses"].get("422")
                    if default is not None and "HTTPValidationError" in json.dumps(default):
                        del operation["responses"]["422"]
            for name in ("HTTPValidationError", "ValidationError"):
                schema.get("components", {}).get("schemas", {}).pop(name, None)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi


def create_app(deps: Dependencies) -> FastAPI:
    # Sem documentação interativa nem `/openapi.json` no processo: o contrato é o arquivo versionado
    # `openapi.json` (superfície mínima, `AGENTS.md` §4).
    app = FastAPI(
        title="smarkee sum service api",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    _install_openapi(app)

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, error: ApiError) -> JSONResponse:
        body: dict[str, Any] = {"errorCode": error.error_code, "message": error.message}
        if error.field is not None:
            body["field"] = error.field
        return JSONResponse(body, status_code=error.status.value, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0]
        # Só o caminho do campo e a regra violada: nunca o valor enviado (`SCHEMA.md` §20.5).
        # Só nomes de campo: em JSON quebrado o `loc` traz a posição do erro, que não é um campo.
        field = ".".join(part for part in first["loc"][1:] if isinstance(part, str)) or None
        return await _api_error(
            _request, bad_request(f"Campo inválido: {first['msg']}", field=field)
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        logger.error("unexpected error", exc_info=error)
        return await _api_error(
            _request, ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "InternalError", "Erro interno.")
        )

    async def authenticated(
        authorization: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization is None or not authorization.startswith("Bearer "):
            raise unauthorized()
        return await deps.verifier.verify(authorization.removeprefix("Bearer ").strip())

    def require(principal: Principal, role: str) -> None:
        if not principal.has_role(role):
            raise forbidden()

    async def require_no_dependents(principal: Principal, service: str) -> None:
        """Desabilitar só segue se nada do dono depender do serviço (decisão 0040).

        Com isso, serviço desabilitado quer dizer "sem recursos dele", e quem verifica a conta
        (o User) pode ler a falta de permissão no módulo como "nada atrelado". Na dúvida, não segue.
        """
        try:
            count = await deps.dependents.count(service, principal.access_token)
        except DependentsCheckError as error:
            if error.retryable:
                raise unavailable() from None
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesNotVerifiable",
                f"Não foi possível verificar os recursos do serviço {service}: falta permissão.",
            ) from None
        if count:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                f"O serviço {service} tem {count} recurso(s) atrelado(s). Remova-os antes de "
                "desabilitar.",
            )

    async def owned_link(principal: Principal, resource_id: str) -> dict[str, Any]:
        """A ligação do solicitante. De outro dono é `404`, para não revelar que ela existe."""
        row = await deps.repository.link(validate_resource_id(resource_id))
        if row is None or _owner(row) != principal.subject:
            raise not_found()
        return row

    async def accept(
        *,
        principal: Principal,
        operation_type: str,
        resource_id: str,
        digest: str,
        idempotency_key: str | None,
        requested: Callable[[str], tuple[str, dict[str, Any]]],
    ) -> JSONResponse:
        operation_id = (
            operation_id_for(principal.subject, idempotency_key)
            if idempotency_key is not None
            else new_identifier()
        )
        if idempotency_key is not None:
            seen = await deps.repository.operation(operation_id)
            if seen is not None:
                if seen["request_digest"] != digest:
                    raise unprocessable("A chave de idempotência já foi usada com outro pedido.")
                return _accepted(seen["resource_id"], operation_id)
        subject, data = requested(operation_id)
        envelope = _requested_envelope(
            principal=principal,
            operation_type=operation_type,
            resource_id=resource_id,
            operation_id=operation_id,
            digest=digest,
            data=data,
            occurred_at=deps.now(),
        )
        await deps.publisher.publish(subject, envelope, message_id=operation_id)
        return _accepted(resource_id, operation_id)

    @app.get("/health/live")
    async def live() -> JSONResponse:
        return _probe(deps.health.live())

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        return _probe(deps.health.ready())

    @app.get("/health/startup")
    async def startup() -> JSONResponse:
        return _probe(deps.health.startup())

    @app.post(
        "/v1/sum/services",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        responses=_errors(400, 401, 403, 409, 422, 503),
    )
    async def create_service(
        principal: Annotated[Principal, Depends(authenticated)],
        body: generated.ServiceCreateRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        service = validate_service(body.service)
        _check_key(idempotency_key)
        digest = request_digest(
            {"operation": "create", "service": service, "owner": principal.subject}
        )
        existing_key = idempotency_key is not None and (
            await deps.repository.operation(operation_id_for(principal.subject, idempotency_key))
        )
        pair: tuple[str, str] | None = None
        if not existing_key:
            require(principal, service_role(service, ACTION_ENABLE))
            pair = await deps.repository.link_for_pair(principal.subject, service)
            if pair is not None and pair[1] == "present":
                raise conflict(f"O serviço {service} já está habilitado (resourceId {pair[0]}).")
        # O recurso é o par dono + serviço: religar um desligado reaproveita o mesmo resourceId.
        resource_id = pair[0] if pair is not None else new_identifier()
        return await accept(
            principal=principal,
            operation_type="create",
            resource_id=resource_id,
            digest=digest,
            idempotency_key=idempotency_key,
            requested=lambda _op: (
                _subject(resource_id, "create"),
                {"specification": {"service": service, "ownerAccountId": principal.subject}},
            ),
        )

    @app.get(
        "/v1/sum/services",
        response_model=generated.ServiceListResponse,
        response_model_exclude_none=True,
        responses=_errors(400, 401),
    )
    async def list_services(
        principal: Annotated[Principal, Depends(authenticated)],
        limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    ) -> dict[str, Any]:
        """Ligações do solicitante cujo serviço ele pode ler (`sum.<serviço>.get`)."""
        visible = [
            row
            for row in await deps.repository.links_of(principal.subject)
            if principal.has_role(service_role(_service(row), ACTION_GET))
        ]
        items = [_view(row) for row in visible[:limit]]
        return {"items": items}

    @app.get(
        "/v1/sum/services/{resource_id}",
        response_model=generated.ServiceResource,
        response_model_exclude_none=True,
        responses=_errors(400, 401, 403, 404),
    )
    async def read_service(
        principal: Annotated[Principal, Depends(authenticated)], resource_id: str
    ) -> dict[str, Any]:
        row = await owned_link(principal, resource_id)
        require(principal, service_role(_service(row), ACTION_GET))
        return _view(row)

    @app.delete(
        "/v1/sum/services/{resource_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        responses=_errors(400, 401, 403, 404, 409, 422, 503),
    )
    async def delete_service(
        principal: Annotated[Principal, Depends(authenticated)],
        resource_id: str,
        resource_version: Annotated[str | None, Query(alias="resourceVersion")] = None,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        version = validate_version(resource_version)
        _check_key(idempotency_key)
        row = await owned_link(principal, resource_id)
        service = _service(row)
        digest = request_digest(
            {"operation": "delete", "resourceId": resource_id, "resourceVersion": version}
        )
        if (
            idempotency_key is None
            or await deps.repository.operation(operation_id_for(principal.subject, idempotency_key))
            is None
        ):
            require(principal, service_role(service, ACTION_DISABLE))
            if str(row["resource_version"]) != version:
                raise conflict(
                    "O serviço mudou desde a última leitura. Leia de novo e tente outra vez."
                )
            await require_no_dependents(principal, service)
        return await accept(
            principal=principal,
            operation_type="delete",
            resource_id=resource_id,
            digest=digest,
            idempotency_key=idempotency_key,
            requested=lambda _op: (_subject(resource_id, "delete"), {"resourceVersion": version}),
        )

    @app.get(
        "/v1/sum/services/{resource_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
        responses=_errors(400, 401, 404),
    )
    async def read_operation(
        principal: Annotated[Principal, Depends(authenticated)], resource_id: str, operation_id: str
    ) -> dict[str, Any]:
        row = await deps.repository.operation_of(validate_resource_id(resource_id), operation_id)
        if row is None or row["requested_by"] != principal.subject:
            raise not_found()
        return _operation_view(row)

    return app


def _probe(result: tuple[bool, dict[str, str]]) -> JSONResponse:
    ok, checks = result
    body = {"status": "UP" if ok else "DOWN", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)


def _check_key(key: str | None) -> None:
    if key is not None and not (1 <= len(key) <= MAX_IDEMPOTENCY_KEY):
        raise bad_request(
            "Idempotency-Key deve ter de 1 a 128 caracteres.", field="Idempotency-Key"
        )


def _owner(row: dict[str, Any]) -> str:
    return str(row["desired"]["ownerAccountId"])


def _service(row: dict[str, Any]) -> str:
    return str(row["desired"]["service"])


def _subject(resource_id: str, operation: str) -> str:
    return f"receiver.requested.{MODULE}.{RESOURCE_TYPE}.{resource_id}.{operation}"


def _accepted(resource_id: str, operation_id: str) -> JSONResponse:
    return JSONResponse(
        {"resourceId": str(resource_id), "operationId": operation_id}, status_code=202
    )


def _requested_envelope(
    *,
    principal: Principal,
    operation_type: str,
    resource_id: str,
    operation_id: str,
    digest: str,
    data: dict[str, Any],
    occurred_at: Any,
) -> bytes:
    """Envelope do `requested` do Receiver, validado pelo contrato antes de sair."""
    now = occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    document: dict[str, Any] = {
        "messageId": new_identifier(),
        "schemaVersion": SCHEMA_VERSION,
        "messageType": "requested",
        "emitter": "receiver",
        "module": MODULE,
        "resourceType": RESOURCE_TYPE,
        "resourceId": resource_id,
        "operation": operation_type,
        "requestedBy": principal.subject,
        "correlationId": new_identifier(),
        "occurredAt": now,
        "publishedAt": now,
        "publishedBy": PUBLISHED_BY,
        "data": {"operationId": operation_id, "requestDigest": digest, **data},
    }
    generated.MessageEnvelope.model_validate(document)
    return json.dumps(document).encode()


def _view(row: dict[str, Any]) -> dict[str, Any]:
    document = {
        "resourceId": str(row["resource_id"]),
        "resourceVersion": str(row["resource_version"]),
        "desiredGeneration": int(row["desired_generation"]),
        "phase": str(row["phase"]),
        "conditions": row["conditions"],
        "desired": row["desired"],
        "createdAt": row["created_at"].isoformat(),
        "updatedAt": row["updated_at"].isoformat(),
    }
    if row.get("observed") is not None:
        document["observed"] = row["observed"]
    return document


def _operation_view(row: dict[str, Any]) -> dict[str, Any]:
    document: dict[str, Any] = {
        "operationId": row["operation_id"],
        "operationType": row["operation_type"],
        "module": MODULE,
        "resourceType": RESOURCE_TYPE,
        "resourceId": str(row["resource_id"]),
        "operationStatus": row["operation_status"],
        "createdAt": row["created_at"].isoformat(),
        "updatedAt": row["updated_at"].isoformat(),
    }
    # Recusada não tem geração: o pedido não chegou a mudar o `desired`.
    if row.get("desired_generation") is not None:
        document["desiredGeneration"] = int(row["desired_generation"])
    if row.get("operation_status_reason") is not None:
        document["operationStatusReason"] = row["operation_status_reason"]
    if row.get("completed_at") is not None:
        document["completedAt"] = row["completed_at"].isoformat()
    return document
