"""Core (non-domain) errors raised by configuration and process bootstrap."""

from __future__ import annotations


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid.

    Startup must abort on this error. The platform never substitutes a
    development default for a missing production value.
    """

    def __init__(self, message: str, *, key: str | None = None) -> None:
        self.key = key
        super().__init__(message if key is None else f"{message} (setting: {key})")
