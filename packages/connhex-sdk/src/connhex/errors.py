import httpx


class ConnhexError(Exception):
    """Base class for Connhex SDK errors."""


class InvalidResponseError(ConnhexError):
    """The API returned an invalid payload or pagination continuation."""


class ConnhexAPIError(ConnhexError):
    """Structured error from a Connhex API response."""

    def __init__(
        self,
        status: int,
        detail: str,
        errors: list | None = None,
        *,
        response: httpx.Response,
        request_id: str | None = None,
    ):
        self.status = status
        self.detail = detail
        self.errors = errors or []
        self.response = response
        self.request_id = request_id
        super().__init__(f"Connhex API error {status}: {detail}")


class AuthenticationError(ConnhexAPIError):
    """Authentication failed."""


class PermissionDeniedError(ConnhexAPIError):
    """The authenticated principal does not have access."""


class NotFoundError(ConnhexAPIError):
    """The requested resource was not found."""


class ConflictError(ConnhexAPIError):
    """The request conflicts with the current resource state."""


class UnprocessableEntityError(ConnhexAPIError):
    """The request was valid but could not be processed."""


class RateLimitError(ConnhexAPIError):
    """The API rate limit was exceeded."""


class InternalServerError(ConnhexAPIError):
    """The Connhex API returned a server error."""


class APIConnectionError(ConnhexError):
    """The SDK could not connect to the Connhex API."""

    def __init__(self, detail: str, *, cause: Exception | None = None):
        self.detail = detail
        self.cause = cause
        super().__init__(detail)


class APITimeoutError(APIConnectionError):
    """The request to the Connhex API timed out."""


_STATUS_ERROR_MAP: dict[int, type[ConnhexAPIError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}

_REQUEST_ID_HEADERS = ("x-request-id", "x-correlation-id", "request-id")


def _request_id_from_response(resp: httpx.Response) -> str | None:
    for header in _REQUEST_ID_HEADERS:
        value = resp.headers.get(header)
        if value:
            return value
    return None


def _error_class_for_status(status: int) -> type[ConnhexAPIError]:
    if status >= 500:
        return InternalServerError
    return _STATUS_ERROR_MAP.get(status, ConnhexAPIError)


def raise_for_connhex_response(resp: httpx.Response) -> None:
    """Convert HTTP error responses to structured ConnhexAPIError."""
    if resp.is_success:
        return

    try:
        body = resp.json()
        # JSON:API error format
        errors = body.get("errors", [])
        if errors:
            detail = errors[0].get("detail", resp.reason_phrase)
        else:
            # Ory/non-JSON:API error format
            detail = body.get("error", {}).get("message", resp.reason_phrase)
    except Exception:
        detail = resp.text[:500] if resp.text else resp.reason_phrase
        errors = []

    error_class = _error_class_for_status(resp.status_code)
    raise error_class(
        resp.status_code,
        detail,
        errors,
        response=resp,
        request_id=_request_id_from_response(resp),
    )
