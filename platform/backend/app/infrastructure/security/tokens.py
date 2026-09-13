"""Opaque token minting and keyed hashing.

Rules this module exists to enforce:

* A token handed to a client is high-entropy, opaque and URL-safe; it encodes no
  identity, so it cannot be decoded, tampered with or trusted on its own.
* Only a *keyed* hash (HMAC-SHA256 with a server-side pepper) is persisted. A
  database disclosure therefore does not yield usable session or reset tokens.
* Comparison is always constant-time, and lookups are performed *by hash*, so no
  code path compares secrets with ``==``.
* Client network identifiers are stored only as keyed hashes, so security records
  remain correlatable without retaining raw addresses.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

#: 32 bytes of entropy, URL-safe. Long enough that guessing is not a threat model.
TOKEN_BYTES = 32


class TokenHasher:
    """Keyed hashing for tokens and client attributes."""

    def __init__(self, pepper: str) -> None:
        if not pepper:
            raise ValueError("a token pepper is required")
        self._pepper = pepper.encode("utf-8")

    def mint(self) -> str:
        return secrets.token_urlsafe(TOKEN_BYTES)

    def hash(self, token: str) -> str:
        return hmac.new(self._pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def mint_with_hash(self) -> tuple[str, str]:
        token = self.mint()
        return token, self.hash(token)

    def matches(self, token: str, token_hash: str) -> bool:
        return hmac.compare_digest(self.hash(token), token_hash)

    def hash_client_attribute(self, value: str | None) -> str | None:
        """Hash an IP address or similar identifier for security records."""
        if not value:
            return None
        return self.hash(f"client:{value}")


def summarize_user_agent(raw: str | None, *, limit: int = 255) -> str | None:
    """Keep a short, non-identifying summary of the client agent."""
    if not raw:
        return None
    return raw.strip()[:limit]


__all__ = ["TOKEN_BYTES", "TokenHasher", "summarize_user_agent"]
