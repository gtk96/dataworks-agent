"""Safe, typed failures raised by external read-only providers."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base error with a stable code safe to expose in logs and API responses."""

    def __init__(self, code: str, reason: str, *, provider: str) -> None:
        self.code = code
        self.reason = reason
        self.provider = provider
        super().__init__(f"{provider}: {code}: {reason}")


class ProviderAuthenticationError(ProviderError):
    """The provider is reachable but current credentials are unusable."""


class ProviderUnavailableError(ProviderError):
    """The provider did not complete a usable read-only request."""
