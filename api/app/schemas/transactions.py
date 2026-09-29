from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.pagination import Page
from app.schemas.common import Money


class PaymentMethod(BaseModel):
    """The method a transaction used.

    The fingerprint (a hash of the card number or wallet address) is deliberately
    NOT here. It is what links accounts together, which makes it exactly the kind of
    value an API should not hand out: it would let anyone with a key join players
    across the whole book.
    """

    id: int
    type: Literal["card", "crypto", "bank"]
    last4: str | None = Field(description="Last four digits, for cards only.")


class Transaction(BaseModel):
    id: int
    direction: Literal["deposit", "withdrawal"]
    amount: Money
    currency: str
    status: Literal["pending", "approved", "rejected", "chargeback"]
    created_at: datetime
    processed_at: datetime | None = Field(description="null while the transaction is pending.")
    method: PaymentMethod


class TransactionPage(Page[Transaction]):
    """A page of transactions."""
