"""Explicit value semantics.

The platform must never conflate "absent", "empty", "NA", "unknown", "not
applicable", zero and false. Collapsing them is the single most common way a
genomic pipeline silently changes the meaning of its input: an absent depth is
not a depth of zero, and an unknown zygosity is not a negative finding.

This module classifies a raw source token into an explicit vocabulary. It never
substitutes a default, never coerces one semantic into another, and never decides
that a missing value is acceptable — that is a validation rule, decided against
the mapping the submitter confirmed.
"""

from __future__ import annotations

from app.domain.value_objects.enums import ValueSemantics

#: Tokens are matched case-insensitively after stripping surrounding whitespace.
#: Each marker maps to exactly one semantic; nothing falls through to "missing".
_NULL_TOKENS = frozenset({"null", "none", "nil", r"\n"})
_NA_TOKENS = frozenset({"na", "n/a", "n.a.", "#na", "not available"})
_UNKNOWN_TOKENS = frozenset({"unknown", "unk", "?", "undetermined"})
_NOT_APPLICABLE_TOKENS = frozenset({"not_applicable", "not applicable", "n/app", "-"})
_FALSE_TOKENS = frozenset({"false", "f", "no"})
_ZERO_TOKENS = frozenset({"0", "0.0", "0.00", "-0", "+0"})


def classify(raw: str | None) -> ValueSemantics:
    """Classify one source token without altering it.

    ``None`` means the field was absent from the record. An empty string means the
    field was present and empty — a different fact, kept different.
    """
    if raw is None:
        return ValueSemantics.MISSING
    token = raw.strip()
    if token == "":
        return ValueSemantics.EMPTY
    lowered = token.lower()
    if lowered in _NULL_TOKENS:
        return ValueSemantics.NULL
    if lowered in _NA_TOKENS:
        return ValueSemantics.NA
    if lowered in _UNKNOWN_TOKENS:
        return ValueSemantics.UNKNOWN
    if lowered in _NOT_APPLICABLE_TOKENS:
        return ValueSemantics.NOT_APPLICABLE
    if lowered in _ZERO_TOKENS:
        return ValueSemantics.ZERO
    if lowered in _FALSE_TOKENS:
        return ValueSemantics.FALSE
    return ValueSemantics.PRESENT


#: Semantics that mean "there is no usable value here". Zero and false are
#: deliberately excluded: they are real values.
ABSENT_SEMANTICS: frozenset[ValueSemantics] = frozenset(
    {
        ValueSemantics.MISSING,
        ValueSemantics.EMPTY,
        ValueSemantics.NULL,
        ValueSemantics.NA,
        ValueSemantics.UNKNOWN,
        ValueSemantics.NOT_APPLICABLE,
    }
)


def is_absent(semantics: ValueSemantics) -> bool:
    return semantics in ABSENT_SEMANTICS


__all__ = ["ABSENT_SEMANTICS", "classify", "is_absent"]
