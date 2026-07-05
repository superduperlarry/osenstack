from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Money is Decimal end to end. NUMERIC(38, 9) in Postgres; never a float.
MoneyAmount = Annotated[Decimal, mapped_column(Numeric(38, 9), nullable=False)]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {
        str: String,
        datetime: DateTime(timezone=True),
        Decimal: Numeric(38, 9),
    }


# Tables that must reject UPDATE/DELETE at the database level.
APPEND_ONLY_TABLES = ("ledger_entries", "activity_events", "mcp_audit", "policies")
