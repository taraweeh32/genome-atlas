"""Column-mapping rules for tabular imports.

A mapping declares what a source column *means*. That is an application concern:
it records the submitter's declaration and checks it for completeness,
uniqueness and internal consistency. It performs no coordinate normalization, no
allele interpretation and no reference-genome lookup — a mapped column named
``chromosome`` is a declaration, never a verified contig.

Nothing is inferred silently. Suggestions exist to make the UI usable, but an
import can only be submitted once the mapping is confirmed by a human, and the
resulting rows record which decisions were suggested and which were chosen.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import (
    DatasetKind,
    FieldConcept,
    MappingStatus,
)

#: Concepts an import of this dataset kind cannot do without. Anything else the
#: submitter maps is additional declared metadata, not a requirement.
REQUIRED_CONCEPTS: Mapping[DatasetKind, frozenset[FieldConcept]] = {
    DatasetKind.VARIANT_CALLS: frozenset(
        {
            FieldConcept.CHROMOSOME,
            FieldConcept.POSITION,
            FieldConcept.REFERENCE_ALLELE,
            FieldConcept.ALTERNATE_ALLELE,
        }
    ),
    DatasetKind.SAMPLE_MANIFEST: frozenset({FieldConcept.SAMPLE_IDENTIFIER}),
    DatasetKind.PHENOTYPE: frozenset(
        {FieldConcept.SAMPLE_IDENTIFIER, FieldConcept.PHENOTYPE_TERM}
    ),
    DatasetKind.ANNOTATION_INPUT: frozenset(
        {FieldConcept.CHROMOSOME, FieldConcept.POSITION}
    ),
    DatasetKind.DERIVED_RESULT: frozenset(),
    DatasetKind.ALIGNMENT: frozenset(),
    DatasetKind.OTHER: frozenset(),
}

#: Concepts that identify one record and therefore may be mapped only once.
SINGLE_USE_CONCEPTS: frozenset[FieldConcept] = frozenset(
    {
        FieldConcept.CHROMOSOME,
        FieldConcept.POSITION,
        FieldConcept.REFERENCE_ALLELE,
        FieldConcept.ALTERNATE_ALLELE,
        FieldConcept.SAMPLE_IDENTIFIER,
        FieldConcept.GENOTYPE,
        FieldConcept.ZYGOSITY,
        FieldConcept.READ_DEPTH,
        FieldConcept.QUALITY,
        FieldConcept.FILTER_STATUS,
    }
)

#: Concepts that carry no platform meaning and may repeat freely.
REPEATABLE_CONCEPTS: frozenset[FieldConcept] = frozenset(
    {FieldConcept.PASSTHROUGH, FieldConcept.IGNORED}
)

#: Case-insensitive header hints used to *suggest* a concept. A suggestion is
#: never applied on its own; it is offered and must be confirmed.
_HEADER_HINTS: Mapping[str, FieldConcept] = {
    "chrom": FieldConcept.CHROMOSOME,
    "chromosome": FieldConcept.CHROMOSOME,
    "#chrom": FieldConcept.CHROMOSOME,
    "contig": FieldConcept.CHROMOSOME,
    "pos": FieldConcept.POSITION,
    "position": FieldConcept.POSITION,
    "start": FieldConcept.POSITION,
    "ref": FieldConcept.REFERENCE_ALLELE,
    "reference": FieldConcept.REFERENCE_ALLELE,
    "ref_allele": FieldConcept.REFERENCE_ALLELE,
    "alt": FieldConcept.ALTERNATE_ALLELE,
    "alternate": FieldConcept.ALTERNATE_ALLELE,
    "alt_allele": FieldConcept.ALTERNATE_ALLELE,
    "id": FieldConcept.VARIANT_IDENTIFIER,
    "variant_id": FieldConcept.VARIANT_IDENTIFIER,
    "gene": FieldConcept.GENE_SYMBOL,
    "gene_symbol": FieldConcept.GENE_SYMBOL,
    "symbol": FieldConcept.GENE_SYMBOL,
    "transcript": FieldConcept.TRANSCRIPT_IDENTIFIER,
    "feature": FieldConcept.TRANSCRIPT_IDENTIFIER,
    "consequence": FieldConcept.CONSEQUENCE,
    "effect": FieldConcept.CONSEQUENCE,
    "sample": FieldConcept.SAMPLE_IDENTIFIER,
    "sample_id": FieldConcept.SAMPLE_IDENTIFIER,
    "gt": FieldConcept.GENOTYPE,
    "genotype": FieldConcept.GENOTYPE,
    "zygosity": FieldConcept.ZYGOSITY,
    "dp": FieldConcept.READ_DEPTH,
    "depth": FieldConcept.READ_DEPTH,
    "af": FieldConcept.ALLELE_FREQUENCY,
    "allele_frequency": FieldConcept.ALLELE_FREQUENCY,
    "qual": FieldConcept.QUALITY,
    "quality": FieldConcept.QUALITY,
    "filter": FieldConcept.FILTER_STATUS,
    "phenotype": FieldConcept.PHENOTYPE_TERM,
    "hpo": FieldConcept.PHENOTYPE_TERM,
}


@dataclass(frozen=True, slots=True)
class MappingDecision:
    """One requested mapping, before it is validated and persisted."""

    source_column_name: str
    source_column_index: int
    target_concept: FieldConcept
    declared_unit: str | None = None
    notes: str | None = None

    @property
    def status(self) -> MappingStatus:
        if self.target_concept is FieldConcept.IGNORED:
            return MappingStatus.IGNORED
        return MappingStatus.MAPPED


def suggest_concept(header: str) -> FieldConcept | None:
    """Offer a concept for a header, or nothing when there is no clear hint.

    Returning ``None`` is a first-class outcome: a guess dressed up as a decision
    is worse than an unmapped column the submitter must look at.
    """
    key = header.strip().lower().replace(" ", "_").replace("-", "_")
    return _HEADER_HINTS.get(key)


def suggest_mapping(headers: Sequence[str]) -> tuple[MappingDecision, ...]:
    """Suggest a full mapping. Unrecognised columns stay unmapped, not guessed."""
    decisions: list[MappingDecision] = []
    used: set[FieldConcept] = set()
    for index, header in enumerate(headers):
        concept = suggest_concept(header)
        if concept in SINGLE_USE_CONCEPTS and concept in used:
            # A second candidate for a single-use concept is ambiguous, and
            # ambiguity is never resolved by picking the first one.
            concept = None
        if concept is not None:
            used.add(concept)
        decisions.append(
            MappingDecision(
                source_column_name=header,
                source_column_index=index,
                target_concept=concept or FieldConcept.IGNORED,
            )
        )
    return tuple(decisions)


def validate_mapping(
    *,
    kind: DatasetKind,
    headers: Sequence[str],
    decisions: Iterable[MappingDecision],
) -> tuple[MappingDecision, ...]:
    """Reject a mapping that cannot be imported, with every reason listed.

    All problems are reported together rather than one per round trip, because a
    submitter fixing a mapping needs the whole picture.
    """
    resolved = tuple(decisions)
    problems: list[dict[str, object]] = []

    header_count = len(headers)
    seen_indexes = Counter(decision.source_column_index for decision in resolved)
    for index, count in seen_indexes.items():
        if count > 1:
            problems.append({"code": "duplicate_column_decision", "column_index": index})
        if index < 0 or index >= header_count:
            problems.append({"code": "unknown_column_index", "column_index": index})

    for decision in resolved:
        if (
            0 <= decision.source_column_index < header_count
            and headers[decision.source_column_index] != decision.source_column_name
        ):
            problems.append(
                {
                    "code": "column_name_mismatch",
                    "column_index": decision.source_column_index,
                    "expected": headers[decision.source_column_index],
                }
            )

    if len(resolved) != header_count:
        problems.append(
            {
                "code": "incomplete_mapping",
                "expected_columns": header_count,
                "provided_columns": len(resolved),
            }
        )

    concept_counts = Counter(
        decision.target_concept
        for decision in resolved
        if decision.target_concept not in REPEATABLE_CONCEPTS
    )
    for concept, count in concept_counts.items():
        if count > 1 and concept in SINGLE_USE_CONCEPTS:
            problems.append(
                {"code": "concept_mapped_more_than_once", "concept": concept.value}
            )

    mapped = {decision.target_concept for decision in resolved}
    missing = sorted(
        concept.value for concept in REQUIRED_CONCEPTS.get(kind, frozenset()) - mapped
    )
    if missing:
        problems.append({"code": "required_concept_unmapped", "concepts": missing})

    if problems:
        raise ValidationError(
            "the column mapping is not valid for this dataset kind",
            details={"field": "mappings", "problems": problems},
        )
    return resolved


__all__ = [
    "REPEATABLE_CONCEPTS",
    "REQUIRED_CONCEPTS",
    "SINGLE_USE_CONCEPTS",
    "MappingDecision",
    "suggest_concept",
    "suggest_mapping",
    "validate_mapping",
]
