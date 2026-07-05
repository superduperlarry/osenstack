from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, LimitParam, Session, StartingAfterParam
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Balance, ListEnvelope, Owner
from enos.services import owners as owners_service
from enos.services import serialize

router = APIRouter(responses=DEFAULT_RESPONSES)


@router.get("/owner", operation_id="getOwner", tags=["Owner"], response_model=Owner)
async def get_owner(session: Session, principal: CurrentPrincipal):
    owner = await owners_service.get_owner_profile(session, principal)
    return serialize.owner(owner)


@router.get(
    "/balances",
    operation_id="listBalances",
    tags=["Balances & Transfers"],
    response_model=ListEnvelope[Balance],
)
async def list_balances(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
):
    rows, has_more = await owners_service.list_balances(
        session, principal, limit=limit, starting_after=starting_after
    )
    return ListEnvelope[Balance](
        data=[serialize.balance(b) for b in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )
