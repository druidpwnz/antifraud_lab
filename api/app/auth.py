"""API-key authentication, and what each key may do.

A client sends its key in the X-API-Key header. There are two kinds:

  API_KEYS       full access: every read, and creating risk checks
  API_READ_KEYS  read only - the admin panel's kind

Every /v1 request needs one of them (require_api_key, applied once on the router).
An endpoint that does more than read also says which scope it needs
(require_scope). A read key on such an endpoint is a 403, not a 401:

  401  "I don't know who you are"           - no key, or a wrong one
  403  "I know who you are, and you may not" - a real key without the scope

That difference matters to the client. A 401 means fix the credentials; a 403 means
the credentials are fine and retrying with them will never work.

Why a read-only kind at all: least privilege. The admin panel only reads, so it gets
a key that can only read. If that key leaks, it cannot create anything.
"""

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

READ = "read"
CREATE_RISK_CHECKS = "risk_checks:create"

# Declaring the header through fastapi.security (instead of a plain Header()) is what
# puts an "apiKey" security scheme in the OpenAPI spec, and the Authorize button in
# /docs. auto_error=False so that a missing header reaches our own check below and
# gets our error format, instead of FastAPI's built-in 403.
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="A key from API_KEYS (full access) or API_READ_KEYS (read only).",
)


@dataclass(frozen=True)
class Caller:
    """Who is calling, as far as the API cares: what they may do."""

    scopes: frozenset[str]


def require_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> Caller:
    """Reject the request with 401 unless it carries a valid key; return its scopes.

    Missing and wrong keys get the SAME response. Saying "wrong key" versus "no key"
    tells a caller probing the API which of the two it got right.
    """
    settings = request.app.state.settings
    # Both lists are checked every time, even when the first matches, so the time a
    # request takes does not reveal which kind of key it carried.
    full = api_key is not None and _matches_any(api_key, settings.api_keys)
    read = api_key is not None and _matches_any(api_key, settings.api_read_keys)

    if full:
        return Caller(frozenset({READ, CREATE_RISK_CHECKS}))
    if read:
        return Caller(frozenset({READ}))
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Missing or invalid API key.",
        # RFC 9110 requires 401 to say how to authenticate. There is no registered
        # scheme for API keys; this form is the common convention.
        headers={"WWW-Authenticate": 'ApiKey header="X-API-Key"'},
    )


def require_scope(scope: str):
    """A dependency that lets the request through only if its key has `scope`.

    It depends on require_api_key itself, so it works on any route. FastAPI runs a
    dependency once per request however many times it is asked for, so the key is
    still only checked once even though the /v1 router asks for it too.
    """

    def check(caller: Caller = Depends(require_api_key)) -> Caller:
        if scope not in caller.scopes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This API key is not allowed to do this (needs the '{scope}' scope).",
            )
        return caller

    return check


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
