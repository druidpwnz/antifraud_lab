from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.pagination import Page

EventStatus = Literal["scheduled", "live", "finished", "cancelled", "postponed"]


class EventSummary(BaseModel):
    id: int
    sport: str
    league: str
    home_team: str
    away_team: str
    start_time: datetime
    status: EventStatus
    finished_at: datetime | None


class EventPage(Page[EventSummary]):
    """A page of events."""


class Selection(BaseModel):
    id: int
    outcome: str = Field(examples=["home"])
    name: str = Field(examples=["Arsenal"])
    current_odds: Decimal = Field(
        description="The price now. It moves until kickoff; a bet keeps the price it "
        "was placed at.",
        examples=["2.25"],
    )
    status: Literal["open", "won", "lost", "void"]


class Market(BaseModel):
    id: int
    type: str = Field(examples=["1x2"])
    line: Decimal = Field(examples=["2.50"])
    status: Literal["open", "suspended", "settled", "void"]
    selections: list[Selection]


class EventDetail(EventSummary):
    """One event with every market and every selection in it."""

    markets: list[Market]
