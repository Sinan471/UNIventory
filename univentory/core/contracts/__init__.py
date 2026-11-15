"""Shared contracts frozen at Increment 1 (plan Section 9).

Owner: Jesher. Consumers import these types; they never import another
module's models to mutate them. Add a versioned field rather than renaming a
consumed one.
"""
from .actor import ActorContext
from .errors import (
    DomainError,
    DuplicateOperationConflict,
    HiddenRecord,
    NotPermitted,
    StaleVersion,
    StockConflict,
    ValidationFailed,
)
from .registry import get_adapter

CONTRACT_VERSION = "1.0"

__all__ = [
    "ActorContext",
    "CONTRACT_VERSION",
    "DomainError",
    "DuplicateOperationConflict",
    "HiddenRecord",
    "NotPermitted",
    "StaleVersion",
    "StockConflict",
    "ValidationFailed",
    "get_adapter",
]
