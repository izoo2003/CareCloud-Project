"""Domain exceptions. HTTP handlers and tool handlers translate these."""


class AppError(Exception):
    """Base class for expected application failures."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFound(AppError):
    """Requested resource does not exist or is soft-deleted."""


class ValidationFailed(AppError):
    """Input failed a business or schema rule after parsing."""

    def __init__(
        self,
        message: str = "Invalid input",
        details: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details or []


class DatabaseUnavailable(AppError):
    """Database could not be reached or rejected the connection."""

    def __init__(self, message: str = "Database unavailable") -> None:
        super().__init__(message)
