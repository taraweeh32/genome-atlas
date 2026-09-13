"""Canonical variant identity.

Identity is the tuple

    reference context + contig + start + end + reference allele + alternate
    allele + variant class + normalization identity

and nothing else. In particular:

* An rsID, a ClinVar accession, an HGVS string or an internal accession is an
  *identifier of* a variant, never the identity of one. Two records that share an
  rsID are not thereby the same variant, and a variant without an rsID is not
  thereby unidentified. Those live in ``VariantExternalIdentifier``.
* The genome build is part of identity. ``chr1:12345:A:G`` in GRCh37 and the same
  string in GRCh38 are different variants, and this module has no way to express
  "the same variant in another build" — cross-build equivalence is a liftover
  claim, which is a scientific computation and therefore out of scope here.
* Normalization identity is part of identity too, because "the canonical form"
  is only canonical *with respect to a stated normalization procedure*. A record
  normalized by a different engine version is a different canonical record, and
  the two coexist rather than overwrite each other.

``canonical_key`` exists purely so that the identity tuple can be indexed and
looked up as one column. It is a rendering, not the identity, and it is
deliberately built from the same fields in a fixed order so that it is stable
across processes, languages and releases.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import NormalizationState, VariantClass

#: Separator that cannot occur inside a contig name, an allele string or a
#: version identifier, so the rendered key can never be ambiguous.
KEY_SEPARATOR = "|"

#: Allele strings are stored verbatim; large symbolic/structural alleles are
#: represented by a symbolic allele plus an end position rather than by a
#: multi-megabase literal.
MAX_ALLELE_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class ContigLabel:
    """A contig as named by the source *and* as named by the reference context.

    Both are kept. ``chr1`` and ``1`` are the same contig only relative to a
    reference genome's naming convention, and deciding that is a reference-data
    question answered by the scientific subsystem. The application therefore
    stores the source spelling for reproducibility and the engine-declared
    spelling for identity — and never rewrites one into the other itself.
    """

    #: Spelling declared by the reference context; part of canonical identity.
    canonical: str
    #: Spelling as it appeared in the source file. ``None`` when the record did
    #: not come from a file (e.g. it was retrieved from a knowledge resource).
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.canonical.strip():
            raise ValidationError("contig name is required", field="contig")
        if KEY_SEPARATOR in self.canonical:
            raise ValidationError(
                "contig name may not contain the identity separator", field="contig"
            )

    @property
    def differs_from_source(self) -> bool:
        """True when the source spelled the contig differently.

        Surfaced in the UI as provenance, not as a warning: a differing spelling
        is normal and is not evidence of an error.
        """
        return self.source is not None and self.source != self.canonical


@dataclass(frozen=True, slots=True)
class CanonicalVariantIdentity:
    """The identity tuple of a canonical variant record.

    Positions are 1-based inclusive, matching the genomic convention the
    reference resources use. ``end_position`` is explicit rather than derived
    from the allele lengths: for symbolic and structural records there is no
    literal allele to derive it from, and deriving it for the others would mean
    the application had opinions about allele arithmetic.
    """

    reference_genome_resource_id: str
    contig: ContigLabel
    position: int
    reference_allele: str
    alternate_allele: str
    variant_class: VariantClass
    normalization_state: NormalizationState
    #: Identity of the procedure that produced this representation. Required even
    #: when the state is ``not_normalized``, where it records *which* engine
    #: declared that it had not normalized the record.
    normalization_version: str
    end_position: int | None = None
    #: ``<DEL>``, ``<DUP>``, ``<INS>``… as declared by the source or the engine.
    symbolic_allele: str | None = None
    structural_variant_type: str | None = None

    def __post_init__(self) -> None:
        if not self.reference_genome_resource_id:
            raise ValidationError(
                "a variant is only identified relative to a reference genome",
                field="reference_genome_resource_id",
            )
        if self.position < 1:
            raise ValidationError("position must be 1-based", field="position")
        if self.end_position is not None and self.end_position < self.position:
            raise ValidationError(
                "end position precedes start position", field="end_position"
            )
        if not self.normalization_version.strip():
            raise ValidationError(
                "the normalization procedure must be identified",
                field="normalization_version",
            )
        for name, allele in (
            ("reference_allele", self.reference_allele),
            ("alternate_allele", self.alternate_allele),
        ):
            if KEY_SEPARATOR in allele:
                raise ValidationError(
                    "allele may not contain the identity separator", field=name
                )
            if len(allele) > MAX_ALLELE_LENGTH:
                raise ValidationError(
                    "allele exceeds the inline length limit; use a symbolic allele",
                    field=name,
                )
        # A symbolic record has no literal alternate allele to compare against,
        # so it must say where it ends. Without that it is not localizable at all,
        # and guessing an end would be inventing scientific content.
        if self.symbolic_allele is not None and self.end_position is None:
            raise ValidationError(
                "a symbolic allele requires an explicit end position",
                field="end_position",
            )

    @property
    def key(self) -> str:
        return canonical_key(self)

    @property
    def is_normalized(self) -> bool:
        """Whether a normalization actually succeeded for this record.

        Deliberately not "truthy unless failed": ``not_normalized`` and
        ``normalization_unavailable`` are both honest negatives, and a caller that
        needs normalized coordinates must treat them as such.
        """
        return self.normalization_state is NormalizationState.NORMALIZED


def canonical_key(identity: CanonicalVariantIdentity) -> str:
    """Render the identity tuple as one deterministic, indexable string.

    The rendering includes the normalization version, so re-normalizing a dataset
    with a new engine version produces new keys instead of colliding with the
    historical records. Two keys being equal means the two records claim the same
    identity; it does not mean the underlying source records were identical, and
    the source representations are kept separately for exactly that reason.
    """
    parts = (
        identity.reference_genome_resource_id,
        identity.contig.canonical,
        str(identity.position),
        str(identity.end_position) if identity.end_position is not None else "",
        identity.reference_allele,
        identity.alternate_allele,
        identity.symbolic_allele or "",
        identity.variant_class.value,
        identity.normalization_version,
    )
    return KEY_SEPARATOR.join(parts)


__all__ = [
    "KEY_SEPARATOR",
    "MAX_ALLELE_LENGTH",
    "CanonicalVariantIdentity",
    "ContigLabel",
    "canonical_key",
]
