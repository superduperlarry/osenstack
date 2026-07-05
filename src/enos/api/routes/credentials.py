from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, IdempotencyKeyHeader, Session
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Credential, CredentialCreate, CredentialWithSecret, ListEnvelope
from enos.services import agents as agents_service
from enos.services import credentials as credentials_service
from enos.services import serialize

router = APIRouter(tags=["Credentials"], responses=DEFAULT_RESPONSES)


@router.post(
    "/agents/{agent_id}/credentials",
    operation_id="createCredential",
    response_model=CredentialWithSecret,
    status_code=201,
)
async def create_credential(
    agent_id: str,
    body: CredentialCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    agent = await agents_service.get_agent(session, principal, agent_id)
    credential, secret = await credentials_service.issue_agent_credential(
        session, principal, agent, body
    )
    return serialize.credential(credential, secret=secret)


@router.get(
    "/agents/{agent_id}/credentials",
    operation_id="listCredentials",
    response_model=ListEnvelope[Credential],
)
async def list_credentials(agent_id: str, session: Session, principal: CurrentPrincipal):
    agent = await agents_service.get_agent(session, principal, agent_id)
    rows, has_more = await credentials_service.list_agent_credentials(session, principal, agent)
    return ListEnvelope[Credential](
        data=[serialize.credential(c) for c in rows], has_more=has_more, next_cursor=None
    )


@router.post(
    "/credentials/{credential_id}/revoke",
    operation_id="revokeCredential",
    response_model=Credential,
)
async def revoke_credential(
    credential_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    credential = await credentials_service.revoke_credential(session, principal, credential_id)
    return serialize.credential(credential)
