from __future__ import annotations


class PolicyOutputError(ValueError):
    """Raised when a model response cannot become one valid Action."""

    def __init__(self, code: str, message: str, *, raw_output: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.raw_output = raw_output


class ProviderError(RuntimeError):
    """Raised when a model provider request or response fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
