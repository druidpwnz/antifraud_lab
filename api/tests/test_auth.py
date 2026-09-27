"""API-key auth, tested on a small app with one protected route."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import errors
from app.auth import require_api_key
from app.settings import Settings


def make_client(*keys: str) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.state.settings = Settings(database_url="", api_keys=keys, pool_min=1, pool_max=1)

    @app.get("/secret", dependencies=[Depends(require_api_key)])
    def secret():
        return {"ok": True}

    return TestClient(app)


def test_no_key_is_401_with_a_www_authenticate_header():
    response = make_client("good").get("/secret")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == 'ApiKey header="X-API-Key"'


def test_wrong_key_looks_exactly_like_no_key():
    client = make_client("good")

    missing = client.get("/secret")
    wrong = client.get("/secret", headers={"X-API-Key": "bad"})

    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()


def test_right_key_is_let_through():
    response = make_client("good").get("/secret", headers={"X-API-Key": "good"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_any_configured_key_works():
    client = make_client("first", "second")

    assert client.get("/secret", headers={"X-API-Key": "second"}).status_code == 200


def test_non_ascii_key_is_401_not_a_crash():
    # hmac.compare_digest raises TypeError on non-ASCII str. Without comparing bytes,
    # this header would turn into a 500.
    client = TestClient(make_client("good").app, raise_server_exceptions=False)

    response = client.get("/secret", headers={"X-API-Key": "ключ".encode()})

    assert response.status_code == 401


def test_no_keys_configured_means_nobody_gets_in():
    # Fail closed: an empty API_KEYS must not mean "no auth".
    response = make_client().get("/secret", headers={"X-API-Key": ""})

    assert response.status_code == 401


def test_openapi_has_the_api_key_security_scheme():
    spec = make_client("good").get("/openapi.json").json()

    schemes = spec["components"]["securitySchemes"]
    assert schemes["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "One of the keys configured in the API_KEYS environment variable.",
    }
