"""API-key authentication.

A client sends its key in the X-API-Key header. Any key listed in the API_KEYS
environment variable is accepted.

Applied once, as a dependency on the /v1 router, rather than inside each endpoint:
a new endpoint is protected by default, and forgetting a check is not possible.
"""

import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

# Declaring the header through fastapi.security (instead of a plain Header()) is what
# puts an "apiKey" security scheme in the OpenAPI spec, and the Authorize button in
# /docs. auto_error=False so that a missing header reaches our own check below and
# gets our error format, instead of FastAPI's built-in 403.
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="One of the keys configured in the API_KEYS environment variable.",
)


def require_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> None:
    """Reject the request with 401 unless it carries a valid key.

    Missing and wrong keys get the SAME response. Saying "wrong key" versus "no key"
    tells a caller probing the API which of the two it got right.

    401, not 403: 401 means "I don't know who you are", 403 means "I know who you
    are, and you may not do this". With a single kind of key there is no 403 yet.
    """
    configured = request.app.state.settings.api_keys
    if api_key is None or not _matches_any(api_key, configured):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or invalid API key.",
            # RFC 9110 requires 401 to say how to authenticate. There is no
            # registered scheme for API keys; this form is the common convention.
            headers={"WWW-Authenticate": 'ApiKey header="X-API-Key"'},
        )


def _matches_any(candidate: str, configured: tuple[str, ...]) -> bool:
    # hmac.compare_digest takes the same time whether the strings differ in the first
    # character or the last. A plain `==` returns at the first mismatch, and timing
    # enough requests can recover a key one character at a time.
    #
    # Compared as bytes: compare_digest raises TypeError on non-ASCII str, and a
    # header can contain non-ASCII bytes - a crafted header would otherwise be a 500.
    #
    # Every configured key is checked (a list, not any() on a generator) so the time
    # taken does not depend on which key matched.
    wanted = candidate.encode()
    results = [hmac.compare_digest(wanted, key.encode()) for key in configured]
    return any(results)
