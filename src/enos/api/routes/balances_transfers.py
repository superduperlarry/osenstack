from fastapi import APIRouter, Response

from enos.api.deps import (
    CurrentPrincipal,
    IdempotencyKeyHeader,
    LimitParam,
    Session,
    StartingAfterParam,
)
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import (
    Balance,
    FundingInstructions,
    ListEnvelope,
    Transfer,
    TransferCreate,
)
from enos.services import owners as owners_service
from enos.services import serialize
from enos.services import transfers as transfers_service
from enos.services import virtual_accounts as va_service

router = APIRouter(tags=["Balances & Transfers"], responses=DEFAULT_RESPONSES)


@router.get("/agents/{agent_id}/balance", operation_id="getAgentBalance", response_model=Balance)
async def get_agent_balance(agent_id: str, session: Session, principal: CurrentPrincipal):
    balance = await owners_service.get_agent_balance(session, principal, agent_id)
    return serialize.balance(balance)


@router.get(
    "/agents/{agent_id}/funding_instructions",
    operation_id="getFundingInstructions",
    response_model=FundingInstructions,
)
async def get_funding_instructions(agent_id: str, session: Session, principal: CurrentPrincipal):
    return await va_service.funding_instructions(session, principal, agent_id)


@router.post(
    "/transfers",
    operation_id="createTransfer",
    response_model=Transfer,
    status_code=201,
    responses={202: {"model": Transfer, "description": "Transfer requires owner approval per Policy."}},
)
async def create_transfer(
    body: TransferCreate,
    response: Response,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    transfer = await transfers_service.create_transfer(session, principal, body)
    if transfer.status == "pending_approval":
        response.status_code = 202
    return serialize.transfer(transfer)


@router.get("/transfers", operation_id="listTransfers", response_model=ListEnvelope[Transfer])
async def list_transfers(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
    agent_id: str | None = None,
):
    rows, has_more = await transfers_service.list_transfers(
        session, principal, limit=limit, starting_after=starting_after, agent_id=agent_id
    )
    return ListEnvelope[Transfer](
        data=[serialize.transfer(t) for t in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )
