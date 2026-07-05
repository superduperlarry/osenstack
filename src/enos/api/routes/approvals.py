from fastapi import APIRouter

from enos.api.deps import (
    CurrentPrincipal,
    IdempotencyKeyHeader,
    LimitParam,
    Session,
    StartingAfterParam,
)
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Approval, ApprovalDecision, ApprovalStatus, ListEnvelope
from enos.services import approvals as approvals_service
from enos.services import serialize

router = APIRouter(tags=["Approvals"], responses=DEFAULT_RESPONSES)


@router.get("/approvals", operation_id="listApprovals", response_model=ListEnvelope[Approval])
async def list_approvals(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
    status: ApprovalStatus | None = None,
    agent_id: str | None = None,
):
    rows, has_more = await approvals_service.list_approvals(
        session,
        principal,
        limit=limit,
        starting_after=starting_after,
        status=status.value if status else None,
        agent_id=agent_id,
    )
    return ListEnvelope[Approval](
        data=[serialize.approval(a) for a in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )


@router.get("/approvals/{approval_id}", operation_id="getApproval", response_model=Approval)
async def get_approval(approval_id: str, session: Session, principal: CurrentPrincipal):
    approval = await approvals_service.get_approval(session, principal, approval_id)
    return serialize.approval(approval)


@router.post(
    "/approvals/{approval_id}/approve", operation_id="approveApproval", response_model=Approval
)
async def approve_approval(
    approval_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
    body: ApprovalDecision | None = None,
):
    approval = await approvals_service.approve(
        session, principal, approval_id, body.note if body else None
    )
    return serialize.approval(approval)


@router.post(
    "/approvals/{approval_id}/reject", operation_id="rejectApproval", response_model=Approval
)
async def reject_approval(
    approval_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
    body: ApprovalDecision | None = None,
):
    approval = await approvals_service.reject(
        session, principal, approval_id, body.note if body else None
    )
    return serialize.approval(approval)
