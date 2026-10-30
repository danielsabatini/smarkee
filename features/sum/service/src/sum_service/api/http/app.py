"""Aplicação HTTP da API de `sum.service` (decisões 0033, 0098 e 0100).

Veja `docs/loop/RESOURCE-CONTROL-LOOP.md` §6.

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava a ligação e o `desired` no outbox (o Publisher publica depois). Não há Operation: `POST`
responde `201` e `DELETE` responde `202`, ambos com o `Resource`; a convergência se acompanha lendo
o recurso (`observedGeneration`, `phase` e `conditions`). As leituras vêm das views do SSOT.

A ligação é do solicitante: ele lê, liga e desliga só as suas (de outro dono é `404`). A permissão
de cada ação é `sum.<serviço>.<ação>`. As pré-condições que dependem de outros módulos (Billing
Account ao ligar, decisão 0082; nenhum recurso dependente ao desligar `ipm`, decisão 0040) consultam
as projeções locais do `DESIRED`, sem chamada HTTP (decisão 0100).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sum_service.api.domain.admission import Admission
from sum_service.api.domain.attachments import describe_all
from sum_service.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from sum_service.api.domain.principal import (
    ACTION_DISABLE,
    ACTION_ENABLE,
    ACTION_GET,
    Principal,
    service_permission,
)
from sum_service.api.domain.records import ResourceRecord
from sum_service.api.domain.requests import (
    checked_idempotency_key,
    request_digest,
    validate_resource_id,
    validate_service,
)
from sum_service.api.domain.views import service_view
from sum_service.api.http.admission import Rules, admit
from sum_service.api.http.health_routes import register_health_routes
from sum_service.api.http.ports import AdmissionStore, Attachments, Repository
from sum_service.api.http.trace_context import TraceContextMiddleware
from sum_service.common.contracts import generated
from sum_service.common.ids import new_identifier, utc_now
from sum_service.common.logging_config import bind_context
from sum_service.common.service_rules import Catalog

logger = logging.getLogger(__name__)

MAX_LIST_LIMIT = 200

SERVICE_METADATA: dict[str, dict[str, str]] = {
    "ipm": {
        "title": "Identity Provider Manager",
        "description": (
            "Manage organizations, identities, groups, permissions and service accounts."
        ),
    }
}


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    authenticator: Authenticator
    repository: Repository
    admissions: AdmissionStore
    attachments: Attachments
    catalog: Catalog
    clock: Callable[[], datetime] = utc_now
    identifiers: Callable[[], str] = new_identifier
    is_ready: Callable[[], bool] = lambda: True
    """Prontidão das dependências críticas (NATS); usada por `/health/ready`."""


async def authenticate(request: Request) -> Principal:
    deps: Dependencies = request.app.state.dependencies
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    principal = await deps.authenticator.verify(token.strip())
    bind_context(requested_by=principal.subject)
    return principal


Authenticated = Annotated[Principal, Depends(authenticate)]
IdempotencyKey = Annotated[str | None, Header()]
VersionQuery = Annotated[str, Query(alias="resourceVersion", pattern=r"^[0-9]{1,18}$")]


def create_app(deps: Dependencies) -> FastAPI:
    app = FastAPI(title="smarkee sum service api", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.dependencies = deps
    app.add_middleware(TraceContextMiddleware)
    _register_error_handlers(app)
    _register_routes(app, deps)
    register_health_routes(app, lambda: deps.is_ready())
    return app


# ---------------------------------------------------------------------- erros


def _error_response(error: ApiError) -> JSONResponse:
    body = generated.ApiError.model_validate(
        {
            "errorCode": error.error_code,
            "message": error.message,
            **({"field": error.field} if error.field else {}),
        }
    )
    return JSONResponse(
        status_code=error.status,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=error.headers,
    )


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, error: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.warning(
            "request rejected",
            extra={"smarkee.outcome": "rejected", "error.type": error.error_code},
        )
        return _error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(  # pyright: ignore[reportUnusedFunction]
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        first = error.errors()[0]
        # Só o caminho do campo e a regra violada: nunca o valor enviado (`SCHEMA.md` §20.5).
        # Só nomes de campo: em JSON quebrado o `loc` traz a posição do erro, que não é um campo.
        field = ".".join(part for part in first["loc"][1:] if isinstance(part, str)) or None
        return _error_response(bad_request(f"Campo inválido: {first['msg']}", field=field))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, error: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.error("unexpected error", exc_info=error)
        return _error_response(
            ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "InternalError", "Erro interno.")
        )


# ---------------------------------------------------------------------- rotas


def _register_routes(app: FastAPI, deps: Dependencies) -> None:
    def require(principal: Principal, permission: str) -> None:
        if not principal.has_permission(permission):
            raise forbidden()

    def require_synced() -> None:
        """Projeção ainda sincronizando é indisponibilidade temporária, nunca "nada atrelado"."""
        if not deps.attachments.is_synced:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "ProjectionSyncPending",
                "Não foi possível verificar os recursos da conta agora. Tente novamente.",
                headers={"Retry-After": "2"},
            )

    def before_enable(owner_account_id: str) -> None:
        """Habilitar um serviço no SUM exige ao menos uma Billing Account ativa (decisão 0082)."""
        require_synced()
        if not deps.attachments.has_billing_account(owner_account_id):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "BillingAccountRequired",
                "É necessário ter ao menos uma Billing Account ativa para habilitar serviços "
                "no SUM.",
            )

    def before_disable(owner_account_id: str, service: str) -> None:
        """Desabilitar só segue se nada do dono depender do serviço (decisão 0040).

        Com isso, serviço desabilitado quer dizer "sem recursos dele", e quem verifica a conta
        (o User) pode ler a falta de permissão no módulo como "nada atrelado".
        """
        require_synced()
        attached = deps.attachments.of(service, owner_account_id)
        if attached:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                f"O serviço {service} tem recursos atrelados: {describe_all(attached)}. "
                "Remova-os antes de desabilitar.",
            )

    def rules() -> Rules:
        # Montadas por requisição: a descrição do OpenAPI não tem dependências reais.
        return Rules(
            catalog=deps.catalog, before_enable=before_enable, before_disable=before_disable
        )

    async def owned_service(principal: Principal, resource_id: str) -> ResourceRecord:
        """A ligação do solicitante. De outro dono é `404`, para não revelar que ela existe."""
        record = await deps.repository.get_service(validate_resource_id(resource_id))
        if record is None or record.desired.get("ownerAccountId") != principal.subject:
            raise not_found()
        return record

    def admission_for(
        requested_by: str,
        operation: Literal["create", "delete"],
        resource_id: str,
        idempotency_key: str | None,
        content: dict[str, Any],
        **extra: Any,
    ) -> Admission:
        return Admission(
            operation=operation,
            resource_id=resource_id,
            requested_by=requested_by,
            correlation_id=deps.identifiers(),
            request_digest=request_digest(content),
            now=deps.clock(),
            message_id=deps.identifiers(),
            idempotency_key=checked_idempotency_key(idempotency_key),
            **extra,
        )

    # ------------------------------------------------------------ serviços

    @app.post(
        "/v1/sum/services",
        status_code=201,
        response_model=generated.ServiceResource,
        response_model_exclude_none=True,
    )
    async def create_service(
        body: generated.ServiceCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ServiceResource:
        service = validate_service(body.service)
        require(principal, service_permission(service, ACTION_ENABLE))
        admission = admission_for(
            principal.subject,
            "create",
            deps.identifiers(),
            idempotency_key,
            {"operation": "create", "service": service, "owner": principal.subject},
            service=service,
        )
        return service_view(await admit(deps.admissions, admission, rules()))

    @app.get(
        "/v1/sum/services",
        response_model=generated.ServiceListResponse,
        response_model_exclude_none=True,
    )
    async def list_services(
        principal: Authenticated,
        limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    ) -> generated.ServiceListResponse:
        """Ligações do solicitante cujo serviço ele pode ler (`sum.<serviço>.get`)."""
        visible = [
            record
            for record in await deps.repository.services_of(principal.subject)
            if principal.has_permission(
                service_permission(str(record.desired["service"]), ACTION_GET)
            )
        ]
        return generated.ServiceListResponse.model_validate(
            {"items": [service_view(record) for record in visible[:limit]]}
        )

    @app.get(
        "/v1/sum/services/available",
        response_model=generated.AvailableServicesResponse,
        response_model_exclude_none=True,
    )
    async def list_available_services(
        principal: Authenticated,
    ) -> generated.AvailableServicesResponse:
        """Lista os serviços disponíveis no catálogo da plataforma para serem habilitados."""
        enabled_services = {
            str(record.desired["service"])
            for record in await deps.repository.services_of(principal.subject)
            if record.desired.get("lifecycle") == "present"
        }
        items = [
            {
                "name": name,
                "title": SERVICE_METADATA.get(name, {}).get("title", name.upper()),
                "description": SERVICE_METADATA.get(name, {}).get("description"),
                "state": "enabled" if name in enabled_services else "available",
            }
            for name in sorted(deps.catalog.keys())
        ]
        return generated.AvailableServicesResponse.model_validate({"items": items})

    @app.get(
        "/v1/sum/services/{resource_id}",
        response_model=generated.ServiceResource,
        response_model_exclude_none=True,
    )
    async def get_service(resource_id: str, principal: Authenticated) -> generated.ServiceResource:
        record = await owned_service(principal, resource_id)
        require(principal, service_permission(str(record.desired["service"]), ACTION_GET))
        return service_view(record)

    @app.delete(
        "/v1/sum/services/{resource_id}",
        status_code=202,
        response_model=generated.ServiceResource,
        response_model_exclude_none=True,
    )
    async def delete_service(
        resource_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ServiceResource:
        record = await owned_service(principal, resource_id)
        require(principal, service_permission(str(record.desired["service"]), ACTION_DISABLE))
        if str(record.resource_version) != resource_version:
            raise conflict()
        admission = admission_for(
            principal.subject,
            "delete",
            resource_id,
            idempotency_key,
            {"operation": "delete", "resourceId": resource_id, "resourceVersion": resource_version},
            resource_version=int(resource_version),
        )
        return service_view(await admit(deps.admissions, admission, rules()))
