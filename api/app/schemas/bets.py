from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.pagination import Page
from app.schemas.common import Money

BetStatus = Literal["open", "won", "lost", "void", "cashed_out"]


class BetSummary(BaseModel):
    """A bet as it appears in a list. The legs are in GET /v1/bets/{id}."""

    id: int
    player_id: int
    placed_at: datetime
    stake: Money
    currency: str
    total_odds: Decimal = Field(description="Odds at placement, 3 decimals.", examples=["2.150"])
    status: BetStatus
    payout: Money | None = Field(description="null until the bet is settled.")
    settled_at: datetime | None


class BetSummaryPage(Page[BetSummary]):
    """A page of bets."""


class LegEvent(BaseModel):
    id: int
    league: str
    home_team: str
    away_team: str
    start_time: datetime
    status: str


class LegMarket(BaseModel):
    id: int
    type: str
    line: Decimal = Field(examples=["2.50"])


class Leg(BaseModel):
    """One selection in a bet, with the market and match it belongs to."""

    selection_id: int
    outcome: str
    name: str
    odds_at_placement: Decimal = Field(
        description="The price when the bet was placed. The selection's price has "
        "usually moved since - this is the one that counts.",
        examples=["2.25"],
    )
    selection_status: Literal["open", "won", "lost", "void"]
    market: LegMarket
    event: LegEvent


class Settlement(BaseModel):
    result: Literal["won", "lost", "void", "half_won", "half_lost"]
    payout: Money
    settled_at: datetime


class BetDetail(BaseModel):
    """One bet in full: its legs and, once decided, its settlement."""

    id: int
    player_id: int
    placed_at: datetime
    stake: Money
    currency: str
    total_odds: Decimal = Field(
        description="The product of the legs' odds at placement, 3 decimals.",
        examples=["3.100"],
    )
    status: BetStatus
    legs: list[Leg]
    settlement: Settlement | None = Field(description="null until the bet is settled.")
