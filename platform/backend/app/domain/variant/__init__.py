"""Variant-centric scientific data layer (Package 6).

This package models what the scientific subsystem *said*, never what it should
say. Nothing in here computes a normalization, a consequence, a frequency, a
clinical meaning or a classification: every scientifically derived field arrives
already decided, accompanied by the identity of the engine and the resource
versions that produced it, and the application's job is to keep those facts
distinguishable, attributable and immutable.

Read the modules in this order:

``identity``
    Canonical variant identity and the deterministic key derived from it. The
    identity is a *tuple*, not a string; the key is only a lookup rendering.
``entities``
    The immutable records layered on top of that identity — source
    representations, representation/normalization contexts, transcript contexts,
    sample observations, annotations, population evidence, clinical assertions.
``results``
    The result surface of a scientific execution: result sets, their stored
    artifacts, and the ingestion request that produced them.
``ingestion``
    Structural acceptance of an ingestion payload. Structural, never scientific:
    it checks that a claim is *well-formed and attributed*, and it never checks
    whether the claim is biologically correct.
"""

from __future__ import annotations

from app.domain.variant.entities import (
    ClinicalAssertionRecord,
    GeneReference,
    PopulationFrequencyRecord,
    SampleObservation,
    TranscriptContext,
    TranscriptReference,
    VariantAnnotationRecord,
    VariantExternalIdentifier,
    VariantRecord,
    VariantRepresentation,
    VariantSourceRepresentation,
)
from app.domain.variant.identity import (
    CanonicalVariantIdentity,
    ContigLabel,
    canonical_key,
)
from app.domain.variant.results import (
    ResultArtifactRecord,
    ResultIngestionRequest,
    ResultSetRecord,
)

__all__ = [
    "CanonicalVariantIdentity",
    "ClinicalAssertionRecord",
    "ContigLabel",
    "GeneReference",
    "PopulationFrequencyRecord",
    "ResultArtifactRecord",
    "ResultIngestionRequest",
    "ResultSetRecord",
    "SampleObservation",
    "TranscriptContext",
    "TranscriptReference",
    "VariantAnnotationRecord",
    "VariantExternalIdentifier",
    "VariantRecord",
    "VariantRepresentation",
    "VariantSourceRepresentation",
    "canonical_key",
]
