from fastapi import APIRouter

from enos.api.deps import (
    CurrentPrincipal,
    IdempotencyKeyHeader,
    LimitParam,
    Session,
    StartingAfterParam,
)
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Agent, AgentCreate, AgentStatus, AgentUpdate, ListEnvelope
from enos.services import agents as agents_service
from enos.services import serialize

router = APIRouter(tags=["Agents"], responses=DEFAULT_RESPONSES)


@router.post("/agents", operation_id="createAgent", response_model=Agent, status_code=201)
async def create_agent(
    body: AgentCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    agent = await agents_service.create_agent(session, principal, body)
    return serialize.agent(agent)


@router.get("/agents", operation_id="listAgents", response_model=ListEnvelope[Agent])
async def list_agents(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
    status: AgentStatus | None = None,
):
    rows, has_more = await agents_service.list_agents(
        session, principal, limit=limit, starting_after=starting_after,
        status=status.value if status else None,
    )
    return ListEnvelope[Agent](
        data=[serialize.agent(a) for a in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )


@router.get("/agents/{agent_id}", operation_id="getAgent", response_model=Agent)
async def get_agent(agent_id: str, session: Session, principal: CurrentPrincipal):
    agent = await agents_service.get_agent(session, principal, agent_id)
    return serialize.agent(agent)


@router.patch("/agents/{agent_id}", operation_id="updateAgent", response_model=Agent)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    agent = await agents_service.update_agent(session, principal, agent_id, body)
    return serialize.agent(agent)


@router.post("/agents/{agent_id}/suspend", operation_id="suspendAgent", response_model=Agent)
async def suspend_agent(
    agent_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    agent = await agents_service.set_agent_status(session, principal, agent_id, "suspended")
    return serialize.agent(agent)


@router.post("/agents/{agent_id}/reactivate", operation_id="reactivateAgent", response_model=Agent)
async def reactivate_agent(
    agent_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    agent = await agents_service.set_agent_status(session, principal, agent_id, "active")
    return serialize.agent(agent)
