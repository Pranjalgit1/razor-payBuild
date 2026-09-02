"""Audit trail service.

Every meaningful step in a recovery case's life is recorded here. PRD rule 6
requires that every case have a complete audit trail, and rule 8 requires that
actions *blocked* by the policy guard be recorded too — a refusal is evidence
that the safety boundary worked, so it must be as visible as a success.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import AgentAction
from app.models.enums import ActionStatus


def record_action(
    db: Session,
    *,
    case_id: int,
    action_type: str,
    reasoning: str | None = None,
    status: ActionStatus = ActionStatus.SUCCESS,
    details: dict | None = None,
    flush: bool = True,
) -> AgentAction:
    """Append one entry to a case's audit trail.

    The caller owns the transaction; this flushes so the row gets an id and a
    timestamp but does not commit, letting a whole workflow step be atomic.
    """
    action = AgentAction(
        recovery_case_id=case_id,
        action_type=action_type,
        reasoning=reasoning,
        status=status,
        details=details,
    )
    db.add(action)
    if flush:
        db.flush()
    return action
