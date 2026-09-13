"""Email address handling.

The *normalized* address is the uniqueness authority (Package 2 enforces a
unique index on it); the address as typed is preserved for display and for
correspondence. Normalization is case-folding and whitespace trimming only —
provider-specific tricks such as dropping dots or ``+`` suffixes are deliberately
not applied, because two people may legitimately own such addresses.
"""

from __future__ import annotations

import re

from app.domain.errors import ValidationError

#: Deliberately conservative: one ``@``, a non-empty local part, a dotted domain.
_EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$")

MAX_EMAIL_LENGTH = 320


def normalize_email(raw: str) -> str:
    """Validate and return the normalized form used for uniqueness."""
    candidate = (raw or "").strip()
    if not candidate:
        raise ValidationError("an email address is required", details={"field": "email"})
    if len(candidate) > MAX_EMAIL_LENGTH:
        raise ValidationError("email address is too long", details={"field": "email"})
    if not _EMAIL_PATTERN.match(candidate):
        raise ValidationError("email address is not valid", details={"field": "email"})
    return candidate.casefold()


def clean_email(raw: str) -> tuple[str, str]:
    """Return ``(as_typed, normalized)``."""
    normalized = normalize_email(raw)
    return (raw or "").strip(), normalized


__all__ = ["MAX_EMAIL_LENGTH", "clean_email", "normalize_email"]
