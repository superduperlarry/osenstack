from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import VirtualAccount
from enos.providers import registry
from enos.schemas.money_movement import FundingInstructions, FundingMethod
from enos.schemas.products import VirtualAccountCreate
from enos.services import activity
from enos.services import agents as agents_service
from enos.services.context import Principal
from enos.services.errors import not_found


async def create_virtual_account(
    session: AsyncSession, principal: Principal, agent_id: str, body: VirtualAccountCreate
) -> VirtualAccount:
    principal.require_owner()
    agent = await agents_service.get_agent(session, principal, agent_id)
    partner = registry.get_banking_partner()
    provisioned = partner.provision_virtual_account(
        owner_legal_name=principal.owner.legal_name,
        agent_display_name=agent.display_name,
        agent_id=agent.id,
        currency=body.currency or principal.owner.default_currency,
    )
    va = VirtualAccount(
        id=ids.new_id(ids.VIRTUAL_ACCOUNT),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        provider_ref=provisioned.provider_ref,
        label=body.label,
        account_name=provisioned.account_name,
        account_number=provisioned.account_number,
        bank_name=provisioned.bank_name,
        bank_identifier=provisioned.bank_identifier,
        currency=provisioned.currency,
        supported_rails=provisioned.supported_rails,
        status=provisioned.status,
    )
    session.add(va)
    await session.flush()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="virtual_account.created",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="virtual_account",
        resource_id=va.id,
    )
    return va


async def list_virtual_accounts(
    session: AsyncSession, principal: Principal, agent_id: str
) -> tuple[list[VirtualAccount], bool]:
    principal.require_owner()
    await agents_service.get_agent(session, principal, agent_id)
    q = (
        select(VirtualAccount)
        .where(VirtualAccount.owner_id == principal.owner.id, VirtualAccount.agent_id == agent_id)
        .order_by(VirtualAccount.id.desc())
    )
    return list((await session.execute(q)).scalars()), False


async def get_virtual_account(
    session: AsyncSession, principal: Principal, virtual_account_id: str
) -> VirtualAccount:
    principal.require_owner()
    q = select(VirtualAccount).where(
        VirtualAccount.id == virtual_account_id, VirtualAccount.owner_id == principal.owner.id
    )
    va = (await session.execute(q)).scalar_one_or_none()
    if va is None:
        raise not_found("virtual account", virtual_account_id)
    return va


async def funding_instructions(
    session: AsyncSession, principal: Principal, agent_id: str
) -> FundingInstructions:
    principal.require_scope("balance:read")
    agent = await agents_service.get_agent(session, principal, agent_id)
    q = select(VirtualAccount).where(
        VirtualAccount.owner_id == principal.owner.id,
        VirtualAccount.agent_id == agent.id,
        VirtualAccount.status == "active",
    )
    methods = [
        FundingMethod(
            rail=rail,
            account_name=va.account_name,
            account_number=va.account_number,
            bank_name=va.bank_name,
            bank_identifier=va.bank_identifier,
            currency=va.currency,
            reference=va.id,  # include with the transfer for automatic crediting
        )
        for va in (await session.execute(q)).scalars()
        for rail in (va.supported_rails or [])
    ]
    return FundingInstructions(agent_id=agent.id, methods=methods)
