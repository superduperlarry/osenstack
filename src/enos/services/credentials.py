import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.config import get_settings
from enos.models import Agent, Credential, Owner
from enos.models.base import utcnow
from enos.schemas.identity import CredentialCreate
from enos.services import activity
from enos.services.context import Principal
from enos.services.errors import not_found, unauthorized


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_secret(prefix: str) -> str:
    env = get_settings().environment
    return f"{prefix}_{env}_{secrets.token_urlsafe(24)}"


async def issue_owner_key(session: AsyncSession, owner: Owner, label: str = "owner key") -> tuple[Credential, str]:
    """Bootstrap path (seed script) — owner keys are not a /v1 resource."""
    secret = _new_secret("ok")
    credential = Credential(
        id=ids.new_id(ids.CREDENTIAL),
        owner_id=owner.id,
        agent_id=None,
        kind="owner",
        label=label,
        token_hash=hash_token(secret),
        scopes=[],
        status="active",
    )
    session.add(credential)
    await session.flush()
    return credential, secret


async def issue_agent_credential(
    session: AsyncSession, principal: Principal, agent: Agent, body: CredentialCreate
) -> tuple[Credential, str]:
    principal.require_owner()
    secret = _new_secret("ac")
    credential = Credential(
        id=ids.new_id(ids.CREDENTIAL),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        kind=body.kind,
        label=body.label,
        token_hash=hash_token(secret),
        scopes=[s.value for s in body.scopes],
        status="active",
        expires_at=body.expires_at,
    )
    session.add(credential)
    await session.flush()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="credential.created",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="credential",
        resource_id=credential.id,
        data={"kind": body.kind.value, "scopes": [s.value for s in body.scopes]},
    )
    return credential, secret


async def list_agent_credentials(
    session: AsyncSession, principal: Principal, agent: Agent
) -> tuple[list[Credential], bool]:
    principal.require_owner()
    q = (
        select(Credential)
        .where(
            Credential.owner_id == principal.owner.id,
            Credential.agent_id == agent.id,
        )
        .order_by(Credential.id.desc())
    )
    return list((await session.execute(q)).scalars()), False


async def revoke_credential(
    session: AsyncSession, principal: Principal, credential_id: str
) -> Credential:
    principal.require_owner()
    q = select(Credential).where(
        Credential.id == credential_id, Credential.owner_id == principal.owner.id
    )
    credential = (await session.execute(q)).scalar_one_or_none()
    if credential is None or credential.agent_id is None:  # owner keys aren't revocable via /v1
        raise not_found("credential", credential_id)
    credential.status = "revoked"
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="credential.revoked",
        agent_id=credential.agent_id,
        credential_id=principal.credential.id,
        resource_type="credential",
        resource_id=credential.id,
    )
    return credential


async def resolve_token(session: AsyncSession, token: str) -> Principal:
    """Bearer token → Principal. Enforces status, expiry, and agent suspension."""
    if not (token.startswith("ok_") or token.startswith("ac_")):
        raise unauthorized()
    q = select(Credential).where(
        Credential.token_hash == hash_token(token), Credential.status == "active"
    )
    credential = (await session.execute(q)).scalar_one_or_none()
    if credential is None:
        raise unauthorized()
    if credential.expires_at is not None and credential.expires_at < utcnow():
        raise unauthorized("Credential has expired.")

    owner = (
        await session.execute(select(Owner).where(Owner.id == credential.owner_id))
    ).scalar_one()

    agent = None
    if credential.agent_id is not None:
        agent = (
            await session.execute(select(Agent).where(Agent.id == credential.agent_id))
        ).scalar_one()
        if agent.status != "active":
            # Suspension freezes the agent: credentials stop authenticating.
            raise unauthorized(f"Agent is {agent.status}.")

    credential.last_used_at = utcnow()
    return Principal(owner=owner, credential=credential, agent=agent)
