"""Liveness and readiness.

Two endpoints because they answer different questions, and an orchestrator treats
them differently:

  /health - is the process alive? Never touches the database. If this fails, restart
            the container.
  /ready  - can it serve traffic? Checks the database. If this fails, stop sending
            requests but do NOT restart: restarting will not fix a database outage.
"""

from fastapi import APIRouter, HTTPException, Request, status

from app import errors

router = APIRouter(tags=["health"])


@router.get("/health", summary="Is the process alive")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Can the API reach the database",
    responses=errors.responses(503),
)
def ready(request: Request) -> dict[str, str]:
    try:
        with request.app.state.pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from None
    return {"status": "ready"}
