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
