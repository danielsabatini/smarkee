"""Erros da API, no formato do contrato `ApiError` (`schemas/common/api-error`)."""

from http import HTTPStatus


class ApiError(Exception):
    """Erro devolvido ao cliente. A mensagem nunca repete valores `confidential`."""

    def __init__(
        self,
        status: HTTPStatus,
        error_code: str,
        message: str,
        *,
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message
        self.field = field
        self.headers = headers or {}


def unauthorized(message: str = "Token ausente ou inválido.") -> ApiError:
    return ApiError(HTTPStatus.UNAUTHORIZED, "Unauthorized", message)


def forbidden(message: str = "O solicitante não tem permissão para esta operação.") -> ApiError:
    return ApiError(HTTPStatus.FORBIDDEN, "Forbidden", message)


def not_found() -> ApiError:
    # Também usado quando o recurso existe mas pertence a outro: não revela a existência.
    return ApiError(HTTPStatus.NOT_FOUND, "NotFound", "Recurso não encontrado.")


def bad_request(message: str, *, field: str | None = None) -> ApiError:
    return ApiError(HTTPStatus.BAD_REQUEST, "ValidationFailed", message, field=field)
