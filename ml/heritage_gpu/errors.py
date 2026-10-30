"""Error taxonomy shared by the client, the runner and the engines."""

from __future__ import annotations


class JobError(Exception):
    """An engine failure with an explicit retry decision.

    ``retryable=False`` dead-letters the job immediately (bad input, unsupported language, too few
    overlapping photos); anything else is retried by the server with exponential backoff.
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class LeaseLostError(ApiError):
    """409 - the lease expired and the job was re-queued, or it was already settled."""


class InvalidResultError(ApiError):
    """422 on complete - the server rejected the result schema and dead-lettered the job."""


class NotRegisteredError(ApiError):
    """404 on a worker-scoped call - e.g. the server database was reset; register again."""


class JobCancelledError(Exception):
    """Raised inside an engine (via ``JobIO.check_cancelled``) once the lease is known to be lost."""
