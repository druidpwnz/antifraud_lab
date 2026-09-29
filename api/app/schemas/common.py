"""Types shared by several schemas."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema

# Money goes out as a string with exactly two decimals: "105.00", "0.00", "-12.50".
#
# A string, because a JSON number is a float to most clients, and floats cannot hold
# 0.10 exactly - the same reason the schema stores money as numeric, not double.
# Exactly two decimals, because a plain Decimal("0") would serialise as "0" and a
# client would have to cope with both shapes.
Money = Annotated[
    Decimal,
    PlainSerializer(
        lambda d: str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        return_type=str,
        when_used="json",
    ),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["105.00"]},
        mode="serialization",
    ),
]
