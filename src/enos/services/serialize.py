"""Model → spec-schema converters. All money leaves as decimal strings."""

from decimal import Decimal

from enos import models, schemas


def money(amount: Decimal | str, currency: str) -> schemas.Money:
    # format(…, "f") keeps fixed-point notation — str(Decimal("0E-9")) would
    # emit scientific notation and violate the Money pattern.
    return schemas.Money(amount=format(Decimal(amount), "f"), currency=currency)


def owner(m: models.Owner) -> schemas.Owner:
    return schemas.Owner(
        id=m.id,
        type=m.type,
        legal_name=m.legal_name,
        display_name=m.display_name,
        verification_status=m.verification_status,
        country=m.country,
        default_currency=m.default_currency,
        created_at=m.created_at,
    )


def agent(m: models.Agent) -> schemas.Agent:
    return schemas.Agent(
        id=m.id,
        owner_id=m.owner_id,
        display_name=m.display_name,
        description=m.description,
        status=m.status,
        policy_version=m.policy_version,
        metadata=m.metadata_ or {},
        created_at=m.created_at,
    )


def credential(m: models.Credential, secret: str | None = None):
    kwargs = dict(
        id=m.id,
        agent_id=m.agent_id,
        kind=m.kind,
        label=m.label,
        scopes=m.scopes or [],
        status=m.status,
        last_used_at=m.last_used_at,
        expires_at=m.expires_at,
        created_at=m.created_at,
    )
    if secret is not None:
        return schemas.CredentialWithSecret(**kwargs, secret=secret)
    return schemas.Credential(**kwargs)


def policy(m: models.Policy) -> schemas.Policy:
    doc = schemas.PolicyCreate.model_validate(m.document)
    return schemas.Policy(
        agent_id=m.agent_id,
        version=m.version,
        limits=doc.limits,
        counterparty_allowlist=doc.counterparty_allowlist,
        verified_counterparties_only=doc.verified_counterparties_only,
        merchant_category_allowlist=doc.merchant_category_allowlist,
        currency_allowlist=doc.currency_allowlist,
        approvals=doc.approvals,
        created_at=m.created_at,
    )


def balance(m: models.Balance) -> schemas.Balance:
    return schemas.Balance(
        holder_type=m.holder_type,
        holder_id=m.holder_id,
        available=money(m.available, m.currency),
        pending_out=money(m.pending_out, m.currency),
        currency_breakdown=[schemas.Money.model_validate(part) for part in (m.breakdown or [])],
        updated_at=m.updated_at,
    )


def transfer(m: models.Transfer) -> schemas.Transfer:
    return schemas.Transfer(
        id=m.id,
        source=schemas.BalanceRef(holder_type=m.source_holder_type, holder_id=m.source_holder_id),
        destination=schemas.BalanceRef(
            holder_type=m.destination_holder_type, holder_id=m.destination_holder_id
        ),
        amount=money(m.amount, m.currency),
        status=m.status,
        approval_id=m.approval_id,
        note=m.note,
        created_at=m.created_at,
    )


def quote(m: models.Quote) -> schemas.Quote:
    return schemas.Quote(
        id=m.id,
        agent_id=m.agent_id,
        source_amount=money(m.source_amount, m.source_currency),
        destination_amount=money(m.destination_amount, m.destination_currency),
        rate=str(m.rate.normalize()),
        fees=[
            schemas.money_movement.QuoteFee.model_validate(fee) for fee in (m.fees or [])
        ],
        estimated_arrival=m.estimated_arrival,
        expires_at=m.expires_at,
        created_at=m.created_at,
    )


def payment(m: models.Payment) -> schemas.Payment:
    return schemas.Payment(
        id=m.id,
        agent_id=m.agent_id,
        credential_id=m.credential_id,
        counterparty_id=m.counterparty_id,
        quote_id=m.quote_id,
        source_amount=money(m.source_amount, m.source_currency),
        destination_amount=(
            money(m.destination_amount, m.destination_currency)
            if m.destination_amount is not None and m.destination_currency
            else None
        ),
        status=m.status,
        approval_id=m.approval_id,
        failure_reason=m.failure_reason,
        rail=m.rail,
        reference=m.reference,
        purpose=m.purpose,
        timeline=[schemas.money_movement.TimelineEntry.model_validate(t) for t in (m.timeline or [])],
        created_at=m.created_at,
        completed_at=m.completed_at,
    )


def _mask(identifier: str | None) -> str | None:
    if not identifier:
        return None
    return "••••" + identifier[-4:]


def counterparty(m: models.Counterparty) -> schemas.Counterparty:
    dest = m.destination or {}
    return schemas.Counterparty(
        id=m.id,
        display_name=m.display_name,
        destination_summary=schemas.money_movement.DestinationSummary(
            type=dest.get("type"),
            currency=dest.get("currency"),
            country=dest.get("country"),
            masked_identifier=_mask(dest.get("account_number") or dest.get("ewallet_id")),
        ),
        status=m.status,
        created_by=schemas.money_movement.CreatedBy(
            actor_type=m.created_by_actor_type, actor_id=m.created_by_actor_id
        ),
        created_at=m.created_at,
    )


def card(m: models.Card) -> schemas.Card:
    return schemas.Card(
        id=m.id,
        agent_id=m.agent_id,
        label=m.label,
        form=m.form,
        status=m.status,
        network=m.network,
        last4=m.last4,
        expiry_month=m.expiry_month,
        expiry_year=m.expiry_year,
        created_at=m.created_at,
    )


def virtual_account(m: models.VirtualAccount) -> schemas.VirtualAccount:
    return schemas.VirtualAccount(
        id=m.id,
        agent_id=m.agent_id,
        label=m.label,
        account_name=m.account_name,
        account_number=m.account_number,
        bank_name=m.bank_name,
        bank_identifier=m.bank_identifier,
        currency=m.currency,
        supported_rails=m.supported_rails or [],
        status=m.status,
        created_at=m.created_at,
    )


def approval(m: models.Approval) -> schemas.Approval:
    return schemas.Approval(
        id=m.id,
        agent_id=m.agent_id,
        action_type=m.action_type,
        action_id=m.action_id,
        trigger=m.trigger,
        summary=m.summary or {},
        status=m.status,
        decided_by=m.decided_by,
        decided_at=m.decided_at,
        note=m.note,
        expires_at=m.expires_at,
        created_at=m.created_at,
    )


def activity_event(m: models.ActivityEvent) -> schemas.ActivityEvent:
    return schemas.ActivityEvent(
        id=m.id,
        type=m.type,
        agent_id=m.agent_id,
        credential_id=m.credential_id,
        resource=schemas.ActivityResource(type=m.resource_type, id=m.resource_id),
        data=m.data or {},
        occurred_at=m.occurred_at,
    )


def webhook_endpoint(m: models.WebhookEndpoint, secret: str | None = None):
    kwargs = dict(
        id=m.id,
        url=m.url,
        event_types=m.event_types or [],
        label=m.label,
        status=m.status,
        created_at=m.created_at,
    )
    if secret is not None:
        return schemas.WebhookEndpointWithSecret(**kwargs, secret=secret)
    return schemas.WebhookEndpoint(**kwargs)
