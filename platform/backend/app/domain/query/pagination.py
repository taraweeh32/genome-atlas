"""Deterministic cursor pagination for filtered variant pages.

A cursor is an opaque token that carries two things: the ordering values of the
last row handed out, and a fingerprint of the query that produced it. The
fingerprint matters more than it looks: resuming page 2 of one filter inside a
different filter would silently mix two result sets, so a cursor that does not
belong to the current query is refused rather than reinterpreted.

Nothing here touches SQL. The cursor is a value object; translating it into a
keyset predicate is the analytical layer's job.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from app.domain.errors import ValidationError

#: Version prefix, so a future cursor format is rejected instead of misread.
CURSOR_VERSION = 1

#: A cursor is small by construction; a large one is not ours.
MAX_CURSOR_BYTES = 4096


@dataclass(frozen=True, slots=True)
class PageCursor:
    """The position of the last row of a page, within one specific query."""

    #: Fingerprint of surface + effective filter + ordering. Not a secret; it is
    #: an equality check, and it carries no filter content.
    query_fingerprint: str
    #: Ordering values of the last returned row, in the ordering's own column
    #: order. ``None`` is preserved, because a null sort value is a real position.
    values: tuple[object, ...]

    def encode(self) -> str:
        payload = {
            "v": CURSOR_VERSION,
            "q": self.query_fingerprint,
            "k": [_encodable(value) for value in self.values],
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _encodable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def query_fingerprint(
    *,
    location: str,
    effective_hash: str,
    order_by: tuple[tuple[str, bool], ...],
    ranking_hash: str | None = None,
) -> str:
    """Identity of the exact query a cursor may be resumed within."""
    payload = {
        "location": location,
        "filter": effective_hash,
        "order": [[column, descending] for column, descending in order_by],
        "ranking": ranking_hash,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def decode_cursor(token: str, *, expected_fingerprint: str) -> PageCursor:
    """Decode a cursor, refusing anything that is not ours.

    Every failure produces the same structured validation error: a malformed
    cursor and a cursor from another query are both "this cursor cannot be used
    here", and neither reveals anything about the other query.
    """
    if len(token) > MAX_CURSOR_BYTES:
        raise ValidationError("the pagination cursor is not valid for this query")
    try:
        padding = "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(token + padding))
    except Exception as exc:
        raise ValidationError("the pagination cursor is not valid for this query") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise ValidationError("the pagination cursor is not valid for this query")
    fingerprint = payload.get("q")
    values = payload.get("k")
    if not isinstance(fingerprint, str) or not isinstance(values, list):
        raise ValidationError("the pagination cursor is not valid for this query")
    if fingerprint != expected_fingerprint:
        raise ValidationError("the pagination cursor is not valid for this query")
    return PageCursor(query_fingerprint=fingerprint, values=tuple(values))


__all__ = [
    "CURSOR_VERSION",
    "MAX_CURSOR_BYTES",
    "PageCursor",
    "decode_cursor",
    "query_fingerprint",
]
