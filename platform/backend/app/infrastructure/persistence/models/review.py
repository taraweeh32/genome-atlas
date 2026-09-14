"""Pinned content of an interpretation version.

An interpretation version is an immutable scientific decision context. Two link
tables pin *exactly* what it was decided from, so a later reclassification of a
criterion or a corrected evidence release can never change what a historical
version stood on:

* ``interpretation_version_criteria`` — the exact criterion evaluation rows the
  version included, automated and human alike, each still labelled with its own
  origin.
* ``interpretation_version_evidence`` — the exact evidence item versions those
  criteria and the reviewer's own reasoning rested on, including evidence retained
  as contradicting.

Neither table is a second criterion model or a second evidence model. Both point
at the rows Package 2, Package 9 and Package 10 already own.
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import (
    Base,
    TimestampMixin,
    fk_column,
    id_column,
)


class InterpretationVersionCriterion(Base, TimestampMixin):
    """One criterion evaluation pinned into one interpretation version."""

    __tablename__ = "interpretation_version_criteria"
    __table_args__ = (
        UniqueConstraint(
            "interpretation_version_id",
            "criterion_evaluation_id",
            name="uq_interpretation_version_criteria_version_criterion",
        ),
        Index(
            "ix_interpretation_version_criteria_criterion_evaluation_id",
            "criterion_evaluation_id",
        ),
    )

    id: Mapped[str] = id_column()
    interpretation_version_id: Mapped[str] = fk_column("app.interpretation_versions.id")
    criterion_evaluation_id: Mapped[str] = fk_column("app.criterion_evaluations.id")
    #: Presentation ordering only; it carries no scientific weight.
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)


class InterpretationVersionEvidence(Base, TimestampMixin):
    """One evidence item version pinned into one interpretation version."""

    __tablename__ = "interpretation_version_evidence"
    __table_args__ = (
        UniqueConstraint(
            "interpretation_version_id",
            "evidence_item_id",
            name="uq_interpretation_version_evidence_version_evidence",
        ),
        Index(
            "ix_interpretation_version_evidence_evidence_item_id",
            "evidence_item_id",
        ),
    )

    id: Mapped[str] = id_column()
    interpretation_version_id: Mapped[str] = fk_column("app.interpretation_versions.id")
    evidence_item_id: Mapped[str] = fk_column("app.evidence_items.id")
    #: ``supports`` | ``contradicts`` | ``context``. Disagreement is retained.
    relation: Mapped[str] = mapped_column(String(64), nullable=False, server_default="supports")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["InterpretationVersionCriterion", "InterpretationVersionEvidence"]
