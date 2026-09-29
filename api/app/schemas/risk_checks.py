from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Money

Direction = Literal["deposit", "withdrawal"]
Decision = Literal["approve", "review", "decline"]


class RiskCheckRequest(BaseModel):
    """A transaction the caller is about to make, and wants a decision on."""

    # extra="forbid": {"ammount": 50} is a 422, not silently ignored. A typo in a
    # money field should never quietly turn into "field missing, use a default".
    model_config = ConfigDict(extra="forbid")

    player_id: int = Field(gt=0, examples=[1])
    direction: Direction
    amount: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description='Send as a string, "250.00". A JSON number works, but a string '
        "cannot be rounded by the client's float arithmetic on the way.",
        examples=["250.00"],
    )
    currency: str = Field(pattern="^[A-Z]{3}$", examples=["PLN"])


class Reason(BaseModel):
    code: str = Field(examples=["deposit_velocity"])
    message: str
    points: int = Field(description="What it added to the score. 100 means a hard decline.")


class RiskCheck(BaseModel):
    id: int
    player_id: int
    direction: Direction
    amount: Money
    currency: str
    decision: Decision
    score: int = Field(ge=0, le=100)
    reasons: list[Reason]
    sim_time_at_check: datetime = Field(
        description="The simulated time the check was scored against."
    )
    created_at: datetime = Field(description="The real time the check was made.")
