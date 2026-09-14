"""SCIENTIFIC ANNOTATION CONTRACT (application side only).

The versioned shape in which the scientific subsystem hands *annotation output*
to the application. Like ``app.scientific.results``, this module contains no
scientific algorithm: no consequence prediction, no transcript selection, no HGVS
generation, no frequency computation, no pathogenicity inference. It declares the
vocabulary of annotation claims an external tool may make, and every claim names
the versioned resource it came from.

Rules the application enforces structurally:

* **Resource identity is mandatory.** A claim without an annotation resource key
  and version is unattributable and is refused, never stored with a guess.
* **Reference context is declared.** The genome assembly the annotation was
  produced against arrives stated; the platform never assumes it.
* **Absence is a semantics value.** ``missing`` / ``unknown`` / ``na`` are carried
  as semantics; they are never converted to ``0``, ``""`` or ``false``.
* **Rows stay outside the request.** Large annotation output is referenced as an
  analytical/object artifact; only bounded inline record batches are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Bumped whenever the shapes below change incompatibly. Persisted with every
#: ingested annotation result so an old payload stays interpretable.
ANNOTATION_CONTRACT_VERSION = "1"

#: An inline batch is a convenience for small payloads and control data. Anything
#: larger is delivered as an artifact; this bound is what keeps an ingestion
#: request from becoming an unbounded upload.
MAX_INLINE_ANNOTATION_RECORDS = 5_000


@dataclass(frozen=True, slots=True)
class AnnotationResourceIdentity:
    """The versioned annotation resource a claim came out of."""

    resource_key: str
    resource_version: str
    #: Platform identifier of the registered resource version, when the producer
    #: knows it. Resolution still happens server-side against the registry.
    resource_id: str | None = None
    schema_version: str | None = None
    genome_assembly: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None

    @property
    def is_identified(self) -> bool:
        return bool(self.resource_key and self.resource_version)


@dataclass(frozen=True, slots=True)
class AnnotationFieldValueClaim:
    """One annotation field/value for one variant, typed, with semantics."""

    field_key: str
    value_type: str
    value_semantics: str = "present"
    value_string: str | None = None
    value_number: float | None = None
    value_integer: int | None = None
    value_boolean: bool | None = None
    value_json: dict[str, Any] | None = None
    transcript_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class AnnotationRecordClaim:
    """Everything one annotation resource asserted about one variant.

    ``variant_id`` addresses a canonical variant the platform already stores.
    Linkage is verified before anything is written: an annotation for a variant
    that is not part of the annotated surface is a rejected record, not an
    orphaned row.
    """

    variant_id: str
    values: tuple[AnnotationFieldValueClaim, ...] = ()
    source_variant_key: str | None = None
    origin: str = "generated"
    retrieved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AnnotationArtifactClaim:
    """A produced annotation artifact (Parquet surface, log, manifest)."""

    artifact_key: str
    kind: str = "annotation_table"
    storage_uri: str | None = None
    analytical_location: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    row_count: int | None = None
    column_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnnotationPayload:
    """The annotation output of one scientific execution."""

    contract_version: str
    #: The platform-side annotation run this payload answers.
    annotation_run_id: str
    resource: AnnotationResourceIdentity
    #: The engine/tool that executed the annotation, where one is involved.
    engine_resource_id: str | None = None
    engine_version: str | None = None
    environment_version: str | None = None
    container_image_digest: str | None = None
    node_identity: str | None = None
    scientific_execution_id: str | None = None
    genome_assembly: str | None = None
    parameters_digest: str | None = None
    records: tuple[AnnotationRecordClaim, ...] = ()
    artifacts: tuple[AnnotationArtifactClaim, ...] = ()
    #: The producer's own statement about coverage; never inferred from counts.
    declared_record_count: int | None = None
    completeness: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set by development/mock adapters. Surfaced wherever the data is shown so a
    #: stand-in annotation can never be mistaken for a scientific one.
    is_development_payload: bool = False


__all__ = [
    "ANNOTATION_CONTRACT_VERSION",
    "MAX_INLINE_ANNOTATION_RECORDS",
    "AnnotationArtifactClaim",
    "AnnotationFieldValueClaim",
    "AnnotationPayload",
    "AnnotationRecordClaim",
    "AnnotationResourceIdentity",
]
