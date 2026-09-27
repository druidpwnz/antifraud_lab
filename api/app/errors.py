"""One error format for every failure: RFC 9457 "Problem Details".

Every error the API returns - 400, 401, 404, 422, 500, 503 - has the same shape and
the media type application/problem+json:

    {
      "type": "about:blank",
      "title": "Not Found",
      "status": 404,
      "detail": "Player 999999 does not exist.",
      "instance": "/v1/players/999999"
    }

A client then needs one error parser, not one per endpoint. 422 adds an `errors`
list saying which field was wrong and why.

A 500 says only that something went wrong. The traceback goes to the server log,
never into the response - a stack trace in a response body tells an attacker which
library, which version and which query failed.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")

PROBLEM_JSON = "application/problem+json"


class FieldError(BaseModel):
    """One invalid field in a 422: where it is, what is wrong, and a stable code."""

    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    """RFC 9457 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None


def problem_response(
    request: Request,
    status: int,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Registered for Starlette's HTTPException, not FastAPI's: that is the parent
    # class, so it also catches the 404 for an unknown URL and the 405 for a wrong
    # method, which the router raises before any FastAPI code runs.
    # exc.headers carries things like WWW-Authenticate (401) and Allow (405).
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(request, exc.status_code, detail, headers=exc.headers)


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # exc.errors() also holds the rejected input and internal context objects.
    # Copy out only the three fields a client needs: echoing input back can leak
    # whatever the caller sent, and the context is not always JSON-serialisable.
    errors = [
        FieldError(loc=list(e["loc"]), msg=e["msg"], type=e["type"])
        for e in exc.errors()
    ]
    return problem_response(request, 422, "The request is not valid. See `errors`.", errors)


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return problem_response(request, 500, "Something went wrong on our side.")


def responses(*codes: int) -> dict[int, dict]:
    """OpenAPI `responses=` entries for these error codes, documented as what the
    API really sends: a Problem, as application/problem+json.

    The obvious way - responses={404: {"model": Problem}} - documents them as
    application/json, which is not what the client will receive.
    """
    return {
        code: {
            "description": HTTPStatus(code).phrase,
            "content": {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for code in codes
    }


def install(app: FastAPI) -> None:
    """Register the handlers, and make sure the Problem schema is in the spec."""
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, unhandled_error)

    # responses() points at #/components/schemas/Problem, but FastAPI only adds a
    # model to the spec when some route uses it as `model=`. Nothing does, so without
    # this every error in /docs would be a broken reference.
    build_default_spec = app.openapi

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        spec = build_default_spec()
        schema = Problem.model_json_schema(ref_template="#/components/schemas/{model}")
        nested = schema.pop("$defs", {})
        spec.setdefault("components", {}).setdefault("schemas", {}).update(
            {"Problem": schema, **nested}
        )
        app.openapi_schema = spec
        return spec

    app.openapi = openapi
