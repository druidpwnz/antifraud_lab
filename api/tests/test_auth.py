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
        "description": "A key from API_KEYS (full access) or API_READ_KEYS (read only).",
    }


# ---------------------------------------------------------------- scopes

from app import auth  # noqa: E402
from app.auth import CREATE_RISK_CHECKS, require_scope  # noqa: E402


def make_scoped_client(full=("full",), read=("read",)) -> TestClient:
    """An app shaped like the real one: the key check on the router, and one route
    that needs an extra scope."""
    from fastapi import APIRouter

    app = FastAPI()
    errors.install(app)
    app.state.settings = Settings(database_url="", api_keys=full, api_read_keys=read,
                                  pool_min=1, pool_max=1)
    router = APIRouter(dependencies=[Depends(require_api_key)])

    @router.get("/thing")
    def read_thing():
        return {"ok": True}

    @router.post("/thing", dependencies=[Depends(require_scope(CREATE_RISK_CHECKS))])
    def create_thing():
        return {"created": True}

    app.include_router(router)
    return TestClient(app)


def test_a_read_key_can_read():
    response = make_scoped_client().get("/thing", headers={"X-API-Key": "read"})

    assert response.status_code == 200


def test_a_read_key_cannot_create_403():
    response = make_scoped_client().post("/thing", headers={"X-API-Key": "read"})

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert "risk_checks:create" in response.json()["detail"]
    assert "www-authenticate" not in response.headers    # that header belongs to 401


def test_a_full_key_can_create():
    response = make_scoped_client().post("/thing", headers={"X-API-Key": "full"})

    assert response.status_code == 200


def test_a_wrong_key_is_still_401_not_403():
    # 403 means "I know you, and you may not". A wrong key is not known at all.
    client = make_scoped_client()

    assert client.post("/thing", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.post("/thing").status_code == 401


def test_read_keys_are_optional():
    client = make_scoped_client(read=())

    assert client.get("/thing", headers={"X-API-Key": "full"}).status_code == 200
    assert client.get("/thing", headers={"X-API-Key": "read"}).status_code == 401


def test_the_key_is_checked_once_per_request_not_twice(monkeypatch):
    # Both the router and require_scope ask for require_api_key. FastAPI caches a
    # dependency's result within one request, so it must run once: one comparison
    # against each of the two key lists, not two of each.
    calls = []
    real = auth._matches_any
    monkeypatch.setattr(auth, "_matches_any", lambda c, k: calls.append(k) or real(c, k))

    make_scoped_client().post("/thing", headers={"X-API-Key": "full"})

    assert len(calls) == 2
