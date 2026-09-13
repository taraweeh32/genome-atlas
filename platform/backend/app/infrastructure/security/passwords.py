"""Password hashing.

Argon2id with deployment-tunable parameters. The implementation satisfies the
``PasswordHasher`` port, so no use case knows which algorithm is in use and an
algorithm change is a rehash-on-verify concern rather than a code change at call
sites.

Two properties matter beyond the algorithm choice:

* ``verify`` reports whether the stored hash should be upgraded
  (``needs_rehash``), so parameter increases roll forward as users sign in.
* ``dummy_verify`` performs a real hash computation against a fixed hash, so an
  authentication attempt for a non-existent account costs the same as one for an
  existing account. Without it, response timing enumerates accounts.
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

ALGORITHM = "argon2id"

#: Hash of a fixed, unusable password, used only for constant-cost dummy verify.
_DUMMY_PASSWORD = "constant-time-dummy-password-value"


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    valid: bool
    needs_rehash: bool = False


class Argon2PasswordHasher:
    """Argon2id password hasher."""

    algorithm = ALGORITHM

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost_kib: int = 65536,
        parallelism: int = 1,
    ) -> None:
        self._hasher = Argon2Hasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash(_DUMMY_PASSWORD)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> PasswordVerification:
        try:
            self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return PasswordVerification(valid=False)
        except Exception:  # pragma: no cover - corrupt stored hash
            return PasswordVerification(valid=False)
        return PasswordVerification(
            valid=True, needs_rehash=self._hasher.check_needs_rehash(password_hash)
        )

    def dummy_verify(self) -> None:
        """Spend the same work as a real verification, and discard the result."""
        try:
            self._hasher.verify(self._dummy_hash, "not-the-dummy-password")
        except Exception:  # noqa: BLE001 - the mismatch is the expected outcome
            return


__all__ = ["ALGORITHM", "Argon2PasswordHasher", "PasswordVerification"]
