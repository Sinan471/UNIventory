"""Audit contract consumed by Jesher's modules.

Provider: Sinan's AuditService (audit module), which appends AuditLog and
outbox rows inside the caller's transaction. Until it is installed, a
logging test adapter is configured and labelled as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AuditEntry:
    action: str
    target_type: str
    target_id: str
    actor_id: int | None
    operation_key: str = ""
    correlation_id: str = ""
    outcome: str = "success"
    reason: str = ""
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    target_version: int | None = None


class AuditSink(Protocol):
    def record(self, entry: AuditEntry) -> None:
        """Append inside the current transaction; never update or delete."""

    def record_denied(self, entry: AuditEntry) -> None:
        """Log a denied attempt separately; no business change occurred."""


def audit(action: str, target, actor, *, before=None, after=None, reason: str = "") -> None:
    """Convenience wrapper used by Jesher's services."""
    from .registry import get_adapter

    get_adapter("AUDIT").record(
        AuditEntry(
            action=action,
            target_type=target.__class__.__name__,
            target_id=str(target.pk),
            actor_id=getattr(getattr(actor, "user", actor), "pk", None),
            operation_key=getattr(actor, "operation_key", ""),
            correlation_id=getattr(actor, "correlation_id", ""),
            reason=reason,
            before=before or {},
            after=after or {},
            target_version=getattr(target, "version", None),
        )
    )


def audit_denied(action: str, target_type: str, target_id, actor, reason: str) -> None:
    from .registry import get_adapter

    get_adapter("AUDIT").record_denied(
        AuditEntry(
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            actor_id=getattr(getattr(actor, "user", actor), "pk", None),
            outcome="denied",
            reason=reason,
        )
    )
