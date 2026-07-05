from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, IdempotencyKeyHeader, Session
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Policy, PolicyCreate
from enos.services import agents as agents_service
from enos.services import policies as policies_service

router = APIRouter(tags=["Policies"], responses=DEFAULT_RESPONSES)


@router.get("/agents/{agent_id}/policy", operation_id="getPolicy", response_model=Policy)
async def get_policy(agent_id: str, session: Session, principal: CurrentPrincipal):
    agent = await agents_service.get_agent(session, principal, agent_id)
    return await policies_service.get_active_policy(session, principal, agent)


@router.put("/agents/{agent_id}/policy", operation_id="replacePolicy", response_model=Policy)
async def replace_policy(
    agent_id: str,
    body: PolicyCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    agent = await agents_service.get_agent(session, principal, agent_id)
    return await policies_service.replace_policy(session, principal, agent, body)
