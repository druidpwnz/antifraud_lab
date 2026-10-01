from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.pagination import Page
from app.schemas.common import Money

PlayerStatus = Literal["active", "suspended", "closed", "self_excluded"]


class Player(BaseModel):
    id: int = Field(examples=[4812])
    registered_at: datetime = Field(examples=["2026-08-18T19:42:07Z"])
    country: str = Field(description="ISO 3166-1 alpha-2", examples=["UA"])
    currency: str = Field(description="ISO 4217", examples=["UAH"])
    status: PlayerStatus


class PlayerPage(Page[Player]):
    """A page of players. Subclassed only to give the schema a readable name in
    /docs: Page[Player] on its own shows up as "Page_Player_"."""


class Balance(BaseModel):
    """What a player has, and the four movements that add up to it.

    balance = deposited - withdrawn - staked + paid_out
    """

    player_id: int
    currency: str
    balance: Money
    deposited: Money = Field(description="Approved deposits.")
    withdrawn: Money = Field(
        description="Withdrawals requested, including pending ones: the money leaves the "
        "balance when it is requested, not when the payout is approved."
    )
    staked: Money = Field(description="Every stake, settled or not.")
    paid_out: Money = Field(description="Every settlement payout.")


class Session(BaseModel):
    """One login: when, from where, on what."""

    id: int
    started_at: datetime
    ended_at: datetime | None = Field(description="null while the session is open.")
    ip: str = Field(examples=["203.0.113.42"])
    device_id: str = Field(examples=["5e6d9db3-2217-4f70-b646-9a1f5f7402f2"])
    user_agent: str | None


class SessionPage(Page[Session]):
    """A page of sessions."""


class LinkedPlayer(BaseModel):
    """Another player who shares something with this one - and only how much.

    The device ids and card fingerprints that connect them are compared inside the
    database and never returned: the API answers "these two share a card" without
    handing out the card's fingerprint.
    """

    id: int
    country: str
    status: PlayerStatus
    registered_at: datetime
    shared_devices: int = Field(description="How many devices both have logged in from.")
    shared_payment_methods: int = Field(description="How many payment methods both use.")


class LinkedPlayerPage(Page[LinkedPlayer]):
    """A page of linked players."""
