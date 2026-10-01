"""Risk checks: "should this deposit or withdrawal go through?"

POST scores a proposed transaction against the player's history and stores the
decision. It never writes to the generator's tables - see README, "The write endpoint
is a risk check, not a transaction".

Idempotency
-----------
The client sends an Idempotency-Key header. If a request times out, the client cannot
tell whether it was scored or not, so it retries with the SAME key:

  first time              -> scored, stored, 201 Created + Location
  same key, same body     -> the stored decision, 200 OK + Idempotent-Replayed: true
  same key, other body    -> 422: the client has a bug, and must not get someone
                             else's decision back

A replay returns what was decided then, even if the player's history has changed
since. That is the point: one question, one answer.

Some APIs (Stripe, for one) answer a replay with the original status code, 201 again.
This one uses 200, because a replay creates nothing, and says so in a header.
"""

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from http import HTTPStatus

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from psycopg import sql
from psycopg.types.json import Jsonb

from app import errors, ledger, scoring
from app.auth import CREATE_RISK_CHECKS, require_scope
from app.db import get_conn
from app.routers.players import load_player
from app.schemas.risk_checks import RiskCheck, RiskCheckRequest

router = APIRouter(prefix="/risk-checks", tags=["risk checks"])

RISK_CHECK_COLUMNS = sql.SQL(
    "id, idempotency_key, request_hash, player_id, direction, amount, currency, "
    "decision, score, reasons, sim_time_at_check, created_at"
)
CENT = Decimal("0.01")


@router.post(
    "",
    summary="Score a proposed deposit or withdrawal",
    status_code=HTTPStatus.CREATED,
    response_model=RiskCheck,
    # needs a full-access key; a read-only key is a 403
    dependencies=[Depends(require_scope(CREATE_RISK_CHECKS))],
    responses={
        200: {"model": RiskCheck, "description": "A replay: this Idempotency-Key was "
              "already used with the same body, and this is the decision made then."},
        **errors.responses(403, 404, 503),
    },
)
def create_risk_check(
    body: RiskCheckRequest,
    response: Response,
    idempotency_key: str = Header(
        min_length=1,
        max_length=255,
        description="Any unique string, typically a UUID. Retry with the same key and "
        "you get the same decision back instead of a second check.",
    ),
    conn: psycopg.Connection = Depends(get_conn),
) -> RiskCheck:
    request_hash = hash_request(body)

    # Fast path: a retry. Answered before looking at the player at all - a replay
    # returns the decision made then, not a re-evaluation against today's data.
    existing = find_by_key(conn, idempotency_key)
    if existing is not None:
        return replay(existing, request_hash, response)

    player = load_player(conn, body.player_id)        # 404 if unknown
    sim_time = current_sim_time(conn)                 # 503 if the clock is not set up
    facts = load_facts(conn, player, sim_time)
    result = scoring.score(
        scoring.Proposed(direction=body.direction, amount=body.amount, currency=body.currency),
        facts,
    )

    # ON CONFLICT DO NOTHING is the race-safe half. Two identical requests can both
    # pass the fast path above at the same moment. The UNIQUE constraint lets exactly
    # one INSERT through; the other gets no row back, and answers as a replay.
    row = conn.execute(
        sql.SQL("""
        INSERT INTO risk_checks
            (idempotency_key, request_hash, player_id, direction, amount, currency,
             decision, score, reasons, sim_time_at_check)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING {columns}
        """).format(columns=RISK_CHECK_COLUMNS),
        (idempotency_key, request_hash, body.player_id, body.direction, body.amount,
         body.currency, result.decision, result.score,
         Jsonb([asdict(r) for r in result.reasons]), sim_time),
    ).fetchone()

    if row is None:
        return replay(find_by_key(conn, idempotency_key), request_hash, response)

    # Commit before answering. On the FastAPI version this was built with, the
    # dependency's commit already runs before the response is sent - but that has
    # changed between versions, and a 201 for a row that is not stored yet would be a
    # lie a client could act on.
    conn.commit()
    response.headers["Location"] = f"/v1/risk-checks/{row['id']}"
    return RiskCheck.model_validate(row)


@router.get(
    "/{risk_check_id}",
    summary="One stored risk check",
    response_model=RiskCheck,
    responses=errors.responses(404),
)
def get_risk_check(
    risk_check_id: int = Path(gt=0),
    conn: psycopg.Connection = Depends(get_conn),
) -> RiskCheck:
    row = conn.execute(
        sql.SQL("SELECT {columns} FROM risk_checks WHERE id = %s").format(columns=RISK_CHECK_COLUMNS),
        (risk_check_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Risk check {risk_check_id} does not exist.")
    return RiskCheck.model_validate(row)


# ------------------------------------------------------------------- helpers

def hash_request(body: RiskCheckRequest) -> str:
    """SHA-256 of the body in one canonical form.

    Canonical, so that {"amount": "50"} and {"amount": "50.00"}, or the same fields in
    a different order, count as the same request.
    """
    canonical = {
        "player_id": body.player_id,
        "direction": body.direction,
        "amount": str(body.amount.quantize(CENT)),
        "currency": body.currency,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def find_by_key(conn: psycopg.Connection, key: str) -> dict | None:
    return conn.execute(
        sql.SQL("SELECT {columns} FROM risk_checks WHERE idempotency_key = %s").format(
            columns=RISK_CHECK_COLUMNS
        ),
        (key,),
    ).fetchone()


def replay(existing: dict, request_hash: str, response: Response) -> RiskCheck:
    if existing["request_hash"] != request_hash:
        raise HTTPException(
            422, "This Idempotency-Key was already used with a different request body."
        )
    response.status_code = HTTPStatus.OK
    response.headers["Idempotent-Replayed"] = "true"
    response.headers["Location"] = f"/v1/risk-checks/{existing['id']}"
    return RiskCheck.model_validate(existing)


def current_sim_time(conn: psycopg.Connection):
    """The simulated "now". Velocity windows are measured against it, not now()."""
    row = conn.execute("SELECT sim_time FROM sim_state WHERE id = 1").fetchone()
    if row is None:
        raise HTTPException(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "The simulation clock is not set up yet - run the backfill first.",
        )
    return row["sim_time"]


def load_facts(conn: psycopg.Connection, player: dict, sim_time) -> scoring.Facts:
    p = {"p": player["id"], "now": sim_time}
    totals = ledger.totals(conn, player["id"])

    history = conn.execute(
        """
        SELECT
          -- percentile_disc, not percentile_cont: _disc returns an actual deposit
          -- amount, as numeric. _cont interpolates, and returns double precision.
          (SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY amount)
           FROM transactions
           WHERE player_id = %(p)s AND direction = 'deposit' AND status = 'approved'
             AND created_at <= %(now)s) AS median_deposit,
          (SELECT count(*)
           FROM transactions
           WHERE player_id = %(p)s AND direction = 'deposit'
             AND created_at >  %(now)s - interval '1 hour'
             AND created_at <= %(now)s) AS deposits_last_hour
        """,
        p,
    ).fetchone()

    last_deposit = conn.execute(
        """
        SELECT amount, processed_at
        FROM transactions
        WHERE player_id = %(p)s AND direction = 'deposit' AND status = 'approved'
          AND processed_at <= %(now)s
        ORDER BY processed_at DESC
        LIMIT 1
        """,
        p,
    ).fetchone()

    staked_since = 0
    if last_deposit is not None:
        staked_since = conn.execute(
            """
            SELECT coalesce(sum(stake), 0) AS staked
            FROM bets
            WHERE player_id = %(p)s AND placed_at >= %(since)s AND placed_at <= %(now)s
            """,
            {**p, "since": last_deposit["processed_at"]},
        ).fetchone()["staked"]

    return scoring.Facts(
        now=sim_time,
        player_status=player["status"],
        player_currency=player["currency"],
        registered_at=player["registered_at"],
        balance=ledger.balance(totals),
        median_deposit=history["median_deposit"],
        deposits_last_hour=history["deposits_last_hour"],
        last_deposit_amount=last_deposit["amount"] if last_deposit else None,
        last_deposit_at=last_deposit["processed_at"] if last_deposit else None,
        staked_since_last_deposit=staked_since,
    )
