"""Transport-independent service errors.

The API maps these onto the frozen error shape. Services never import FastAPI.
"""

from __future__ import annotations


class ServiceError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(ServiceError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "Not found.") -> None:
        super().__init__(message)


class ForbiddenError(ServiceError):
    status_code = 403
    code = "forbidden"

    def __init__(self, message: str = "Forbidden.") -> None:
        super().__init__(message)


class DraftVersionConflictError(ServiceError):
    status_code = 409
    code = "draft_version_conflict"

    def __init__(
        self,
        message: str = "The booking details changed. Please confirm the updated summary.",
    ) -> None:
        super().__init__(message)


class ConfirmationRequiredError(ServiceError):
    status_code = 409
    code = "confirmation_required"

    def __init__(
        self, message: str = "The current booking summary has not been confirmed."
    ) -> None:
        super().__init__(message)


class DraftIncompleteError(ServiceError):
    status_code = 422
    code = "draft_incomplete"

    def __init__(self, message: str = "The booking draft is incomplete.") -> None:
        super().__init__(message)


class InvalidBookingDetailsError(ServiceError):
    status_code = 422
    code = "invalid_booking_details"

    def __init__(self, message: str = "The booking details are invalid.") -> None:
        super().__init__(message)


class IdempotencyConflictError(ServiceError):
    status_code = 409
    code = "idempotency_conflict"

    def __init__(
        self, message: str = "The idempotency key was already used for different details."
    ) -> None:
        super().__init__(message)
