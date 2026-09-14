"""Annotation resources, profiles, runs and annotation result versions.

The application's job in annotation is *governance and bookkeeping*: which
annotation resource versions exist, which configuration was used, what an
external scientific tool produced, and how to reach it again unchanged. No
annotation is computed here — this package contains no consequence prediction, no
transcript selection, no HGVS generation, no frequency computation and no
clinical inference of any kind.
"""

from app.domain.annotation.entities import (
    AnnotationFieldSpec,
    AnnotationProfileRecord,
    AnnotationProfileVersionRecord,
    AnnotationResourceRecord,
    AnnotationResultVersionRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
    ProfileResourceBinding,
)
from app.domain.annotation.fields import (
    ANNOTATION_FIELD_PREFIX,
    annotation_field_definitions,
    annotation_field_id,
)
from app.domain.annotation.validation import (
    ACCEPTED_ANNOTATION_CONTRACT_VERSIONS,
    AnnotationValidationOutcome,
    validate_annotation_payload,
)

__all__ = [
    "ACCEPTED_ANNOTATION_CONTRACT_VERSIONS",
    "ANNOTATION_FIELD_PREFIX",
    "AnnotationFieldSpec",
    "AnnotationProfileRecord",
    "AnnotationProfileVersionRecord",
    "AnnotationResourceRecord",
    "AnnotationResultVersionRecord",
    "AnnotationRunRecord",
    "AnnotationValidationFinding",
    "AnnotationValidationOutcome",
    "ProfileResourceBinding",
    "annotation_field_definitions",
    "annotation_field_id",
    "validate_annotation_payload",
]
