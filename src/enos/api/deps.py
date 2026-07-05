"""Route dependencies: principal resolution and shared parameter types."""

from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from enos.db import get_session
from enos.models import Agent, Credential, Owner
from enos.services.context import Principal
from enos.services.errors import unauthorized

Session = Annotated[AsyncSession, Depends(get_session)]


async def current_principal(request: Request, session: Session) -> Principal:
    """Rehydrates the Principal (validated by AuthMiddleware) in the route session."""
    auth = getattr(request.state, "auth", None)
    if auth is None:
        raise unauthorized()
    credential = await session.get(Credential, auth["credential_id"])
    owner = await session.get(Owner, auth["owner_id"])
    agent = await session.get(Agent, auth["agent_id"]) if auth["agent_id"] else None
    return Principal(owner=owner, credential=credential, agent=agent)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

# Documented for spec parity; enforcement happens in IdempotencyMiddleware.
IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=16,
        max_length=128,
        description="Client-generated unique key (UUIDv4 recommended). 24h dedup window keyed by (credential, key).",
    ),
]

LimitParam = Annotated[int, Query(ge=1, le=100)]
StartingAfterParam = Annotated[str | None, Query()]
