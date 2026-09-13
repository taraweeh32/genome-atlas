"""Object-storage key layout.

Keys are derived entirely from server-generated identifiers. No component of a
key ever comes from a client: not the filename, not a path, not a workspace name.
That is what makes a key unguessable in practice and makes tenant separation
visible in storage itself.

A key is also never a capability. Possessing one grants nothing: retrieval always
goes through an authorization check against the artifact's own workspace/project
scope, and only then produces a short-lived presigned URL.
"""

from __future__ import annotations

import re

from app.domain.errors import ValidationError

_IDENTIFIER = re.compile(r"^[a-z]{3}_[0-9a-f]{32}$")

#: Top-level prefixes, so a lifecycle rule or a bucket policy can address one
#: class of object without pattern-matching deep paths.
UPLOAD_PREFIX = "uploads"
QUARANTINE_PREFIX = "quarantine"


def _require_identifier(name: str, value: str) -> str:
    if not _IDENTIFIER.match(value):
        raise ValidationError(
            "malformed identifier for a storage key", details={"field": name}
        )
    return value


def upload_key(
    *,
    workspace_id: str,
    dataset_id: str,
    dataset_version_id: str,
    file_artifact_id: str,
) -> str:
    """Deterministic key for one artifact of one dataset version.

    Including the version identifier keeps an immutable input immutable in
    storage too: a corrected upload lands under a new version's prefix rather
    than overwriting the bytes a historical result was produced from.
    """
    return "/".join(
        (
            UPLOAD_PREFIX,
            _require_identifier("workspace_id", workspace_id),
            _require_identifier("dataset_id", dataset_id),
            _require_identifier("dataset_version_id", dataset_version_id),
            _require_identifier("file_artifact_id", file_artifact_id),
        )
    )


def quarantine_key(*, workspace_id: str, file_artifact_id: str) -> str:
    return "/".join(
        (
            QUARANTINE_PREFIX,
            _require_identifier("workspace_id", workspace_id),
            _require_identifier("file_artifact_id", file_artifact_id),
        )
    )


def workspace_prefix(workspace_id: str) -> str:
    """Prefix used by reconciliation to enumerate one tenant's objects only."""
    return f"{UPLOAD_PREFIX}/{_require_identifier('workspace_id', workspace_id)}/"


__all__ = [
    "QUARANTINE_PREFIX",
    "UPLOAD_PREFIX",
    "quarantine_key",
    "upload_key",
    "workspace_prefix",
]
