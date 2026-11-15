"""Consistent outcomes for every module (Section 9, Errors and Repeat Submissions).

400/422 invalid input, 403 or non-disclosing 404 for denied access, 409 for
stale or conflicting stock. Views translate these into responses; services
raise them.
"""
from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "invalid"
    default_message = "The request could not be completed."

    def __init__(self, message: str = "", *, field_errors: dict | None = None, next_action: str = ""):
        self.message = message or self.default_message
        super().__init__(self.message)
        self.field_errors = field_errors or {}
        self.next_action = next_action


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"
    default_message = "The submitted values are not valid."


class NotPermitted(DomainError):
    status_code = 403
    code = "not_permitted"
    default_message = "You do not have permission for this action."


class HiddenRecord(DomainError):
    status_code = 404
    code = "not_found"
    default_message = "The record does not exist or is not available to you."


class StaleVersion(DomainError):
    status_code = 409
    code = "stale_version"
    default_message = "The record changed after you opened it. Reload to see the current version."


class StockConflict(DomainError):
    status_code = 409
    code = "stock_conflict"
    default_message = "The requested quantity is no longer available."


class DuplicateOperationConflict(DomainError):
    status_code = 409
    code = "operation_key_reused"
    default_message = "This operation key was already used for different input."
