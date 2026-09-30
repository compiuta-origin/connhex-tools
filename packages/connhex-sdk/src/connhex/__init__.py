from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("connhex")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

from connhex.aio._client import AsyncConnhex  # noqa: E402
from connhex.auth import BearerAuth, SessionCookieAuth  # noqa: E402
from connhex.errors import (  # noqa: E402
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    ConnhexAPIError,
    ConnhexError,
    InternalServerError,
    InvalidResponseError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from connhex.sync._client import Connhex  # noqa: E402

__all__ = [
    "APIConnectionError",
    "APITimeoutError",
    "AsyncConnhex",
    "BearerAuth",
    "AuthenticationError",
    "ConflictError",
    "Connhex",
    "ConnhexAPIError",
    "ConnhexError",
    "InternalServerError",
    "InvalidResponseError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "SessionCookieAuth",
    "UnprocessableEntityError",
    "__version__",
]
