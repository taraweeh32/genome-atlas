"""Password policy.

Policy is a domain rule and lives here; *hashing* is a cryptographic concern and
lives behind the ``PasswordHasher`` port (``app/application/ports.py``) with an
Argon2id implementation in infrastructure. The domain never sees a hash and never
sees a cleartext password after validation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import ValidationError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 512


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    min_length: int = MIN_PASSWORD_LENGTH
    max_length: int = MAX_PASSWORD_LENGTH
    require_mixed_case: bool = True
    require_digit: bool = True
    require_symbol: bool = False

    def validate(self, password: str, *, email: str | None = None) -> None:
        """Raise ``ValidationError`` when the password is unacceptable.

        The error never echoes the password back, and the failure detail names
        the unmet requirement rather than describing the stored value.
        """
        if password is None or len(password) < self.min_length:
            raise ValidationError(
                "password is too short",
                details={"field": "password", "min_length": self.min_length},
            )
        if len(password) > self.max_length:
            raise ValidationError(
                "password is too long",
                details={"field": "password", "max_length": self.max_length},
            )
        if self.require_mixed_case and (password.islower() or password.isupper()):
            raise ValidationError(
                "password must mix upper and lower case",
                details={"field": "password", "requirement": "mixed_case"},
            )
        if self.require_digit and not any(character.isdigit() for character in password):
            raise ValidationError(
                "password must contain a digit",
                details={"field": "password", "requirement": "digit"},
            )
        if self.require_symbol and password.isalnum():
            raise ValidationError(
                "password must contain a symbol",
                details={"field": "password", "requirement": "symbol"},
            )
        if email:
            local_part = email.split("@", 1)[0].casefold()
            if local_part and local_part in password.casefold():
                raise ValidationError(
                    "password must not contain the email address",
                    details={"field": "password", "requirement": "not_email_derived"},
                )


DEFAULT_PASSWORD_POLICY = PasswordPolicy()

__all__ = [
    "DEFAULT_PASSWORD_POLICY",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PasswordPolicy",
]
