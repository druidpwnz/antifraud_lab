"""The FastAPI application.

Run from the api/ directory:
    uvicorn app.main:app --reload
Then open http://localhost:8000/docs
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from app import db, errors, settings
from app.auth import require_api_key
from app.routers import bets, events, health, players, risk_checks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Runs once at startup (before `yield`) and once at shutdown (after it)."""
    app.state.settings = settings.load()
    app.state.pool = db.create_pool(app.state.settings)
    try:
        yield
    finally:
        app.state.pool.close()


app = FastAPI(
    title="Antifraud Lab API",
    version="0.1.0",
    summary="Read access to generated betting data, and pre-transaction risk checks.",
    lifespan=lifespan,
)

errors.install(app)

app.include_router(health.router)   # no key needed: orchestrators call these

# Everything under /v1 needs an API key, applied once here instead of per endpoint.
# From step 3 the resource routers are added to `v1` with v1.include_router(...),
# and that has to happen ABOVE app.include_router(v1): FastAPI copies the routes at
# the moment of inclusion, so a route added to `v1` afterwards is silently missing.
v1 = APIRouter(
    prefix="/v1",
    dependencies=[Depends(require_api_key)],
    responses=errors.responses(401, 422, 500),
)
v1.include_router(players.router)
v1.include_router(bets.router)
v1.include_router(events.router)
v1.include_router(risk_checks.router)

app.include_router(v1)
