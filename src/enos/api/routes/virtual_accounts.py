from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, IdempotencyKeyHeader, Session
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import ListEnvelope, VirtualAccount, VirtualAccountCreate
from enos.services import serialize
from enos.services import virtual_accounts as va_service

router = APIRouter(tags=["Virtual Accounts"], responses=DEFAULT_RESPONSES)


@router.post(
    "/agents/{agent_id}/virtual_accounts",
    operation_id="createVirtualAccount",
    response_model=VirtualAccount,
    status_code=201,
)
async def create_virtual_account(
    agent_id: str,
    body: VirtualAccountCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    va = await va_service.create_virtual_account(session, principal, agent_id, body)
    return serialize.virtual_account(va)


@router.get(
    "/agents/{agent_id}/virtual_accounts",
    operation_id="listVirtualAccounts",
    response_model=ListEnvelope[VirtualAccount],
)
async def list_virtual_accounts(agent_id: str, session: Session, principal: CurrentPrincipal):
    rows, has_more = await va_service.list_virtual_accounts(session, principal, agent_id)
    return ListEnvelope[VirtualAccount](
        data=[serialize.virtual_account(v) for v in rows], has_more=has_more, next_cursor=None
    )


@router.get(
    "/virtual_accounts/{virtual_account_id}",
    operation_id="getVirtualAccount",
    response_model=VirtualAccount,
)
async def get_virtual_account(
    virtual_account_id: str, session: Session, principal: CurrentPrincipal
):
    va = await va_service.get_virtual_account(session, principal, virtual_account_id)
    return serialize.virtual_account(va)
