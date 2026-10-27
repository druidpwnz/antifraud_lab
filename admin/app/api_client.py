"""The panel's only way to data: the API, over HTTP.

The panel never touches the database. Everything it shows comes through here, with
the panel's own API key - a read-only one.

One httpx.Client for the whole app: it keeps connections to the API open and reuses
them, the same reason the API keeps a connection pool to Postgres.

Every failure becomes one of two exceptions, so views never deal with httpx:

  ApiUnavailable  the API could not be reached, or did not answer in time
  ApiError        the API answered with an error - status, title and detail come
                  from its problem+json body

What the panel does with each is decided once, in app/__init__.py.
"""

import httpx


class ApiUnavailable(Exception):
    """The API is down, unreachable, or too slow."""


class ApiError(Exception):
    """The API answered, with an error."""

    def __init__(self, status: int, title: str, detail: str | None):
        super().__init__(f"{status} {title}: {detail}")
        self.status = status
        self.title = title
        self.detail = detail

    @classmethod
    def from_response(cls, response: httpx.Response) -> ApiError:
        # Our API always answers errors as problem+json. A proxy in front of it might
        # not, so fall back to the status line rather than crash on a non-JSON body.
        try:
            body = response.json()
        except ValueError:
            body = {}
        return cls(
            status=response.status_code,
            title=body.get("title") or response.reason_phrase or "Error",
            detail=body.get("detail"),
        )


class ApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float,
                 transport: httpx.BaseTransport | None = None):
        # transport is for tests: they pass an httpx.MockTransport, so the panel can be
        # tested with no API running at all.
        self._http = httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def get(self, path: str, **params) -> dict:
        """GET a path, return the JSON body. Empty parameters are left out, so a blank
        filter in a form does not become `?country=` and a 422."""
        params = {k: v for k, v in params.items() if v not in (None, "")}
        try:
            response = self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ApiUnavailable("the API did not answer in time") from exc
        except httpx.TransportError as exc:
            raise ApiUnavailable("the API could not be reached") from exc
        if response.status_code >= 400:
            raise ApiError.from_response(response)
        return response.json()

    def close(self) -> None:
        self._http.close()
