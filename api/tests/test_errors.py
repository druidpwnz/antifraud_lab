"""Every failure comes back as application/problem+json, in one shape."""

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app import errors

PROBLEM_JSON = "application/problem+json"


def make_app() -> FastAPI:
    """A tiny app with the real error handlers and two routes that fail on purpose."""
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("password=hunter2 at /srv/app/secret.py line 42")

    @app.get("/items")
    def items(limit: int = Query(10, ge=1, le=100)):
        return {"limit": limit}

    return app


def test_unknown_url_is_a_problem(client_without_db):
    response = client_without_db.get("/no/such/thing")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == "/no/such/thing"


def test_wrong_method_is_a_problem_and_keeps_the_allow_header(client_without_db):
    response = client_without_db.post("/health")

    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM_JSON
    assert "GET" in response.headers["allow"]


def test_database_down_is_a_problem(client_without_db):
    response = client_without_db.get("/ready")

    assert response.status_code == 503
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json()["detail"] == "database unavailable"


def test_a_crash_is_a_500_that_reveals_nothing():
    # raise_server_exceptions=False: by default TestClient re-raises the error inside
    # the test instead of returning the 500 a real client would receive.
    client = TestClient(make_app(), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json()["detail"] == "Something went wrong on our side."
    assert "hunter2" not in response.text
    assert "secret.py" not in response.text
    assert "RuntimeError" not in response.text


def test_validation_error_says_which_field_and_why_without_echoing_input():
    client = TestClient(make_app())

    response = client.get("/items", params={"limit": 500})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_JSON
    (error,) = response.json()["errors"]
    assert error["loc"] == ["query", "limit"]
    assert error["type"] == "less_than_equal"
    assert "input" not in error


def test_openapi_documents_errors_as_problem_json(client_without_db):
    spec = client_without_db.get("/openapi.json").json()

    assert "Problem" in spec["components"]["schemas"]
    assert "FieldError" in spec["components"]["schemas"]
    content = spec["paths"]["/ready"]["get"]["responses"]["503"]["content"]
    assert content == {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}}
