"""Projection of registered annotation fields into the Package 7 field registry.

Package 7 filters and ranks whatever the field dictionary declares. Annotation
resources declare their own fields when they are registered, so this module turns
those declarations into ordinary ``FilterFieldDefinition`` entries and extends the
existing registry with them.

Two consequences are deliberate:

* the frontend never hardcodes annotation fields — it renders whatever the
  dictionary reports, including fields added long after the UI was written;
* the filtering layer never learns anything scientific — a projected field is a
  typed column with declared operators, a source resource and a version, and
  nothing about what its values mean.

A projected field is available only where the annotated surface actually carries
its column, which is the same honesty rule the shipped dictionary follows.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

from app.domain.annotation.entities import AnnotationFieldSpec, AnnotationResourceRecord
from app.domain.query.fields import (
    FilterFieldCategory,
    FilterFieldDefinition,
    FilterFieldOrigin,
    FilterFieldRegistry,
)
from app.domain.query.operators import FilterDataType
from app.domain.value_objects.enums import AnnotationValueType

#: Namespace for projected fields, so a resource can never shadow a shipped field
#: identifier such as ``chromosome``.
ANNOTATION_FIELD_PREFIX = "annotation"

_DATA_TYPES: dict[AnnotationValueType, FilterDataType] = {
    AnnotationValueType.STRING: FilterDataType.CATEGORICAL,
    AnnotationValueType.INTEGER: FilterDataType.INTEGER,
    AnnotationValueType.NUMBER: FilterDataType.DECIMAL,
    AnnotationValueType.BOOLEAN: FilterDataType.BOOLEAN,
    AnnotationValueType.DATE: FilterDataType.DATETIME,
    #: A structured value is not filterable as a scalar; it is exposed for
    #: display and provenance only.
    AnnotationValueType.JSON: FilterDataType.STRING,
}


def annotation_field_id(resource_key: str, field_key: str) -> str:
    """Stable, namespaced identifier for one resource's field.

    Deliberately excludes the resource *version*: the same field keeps its
    identifier across resource versions, so a saved filter written against
    version 110 still resolves after 111 is published. Which version actually
    produced a value stays recorded on the stored annotation row.
    """

    slug = f"{resource_key}_{field_key}".strip().lower()
    cleaned = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in slug
    )
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return f"{ANNOTATION_FIELD_PREFIX}_{cleaned.strip('_')}"


def annotation_field_definition(
    resource: AnnotationResourceRecord, specification: AnnotationFieldSpec
) -> FilterFieldDefinition:
    data_type = _DATA_TYPES[specification.value_type]
    description = specification.description or (
        f"Annotation field reported by {resource.display_name}, stored verbatim."
    )
    return FilterFieldDefinition(
        id=annotation_field_id(resource.resource_key, specification.field_key),
        label=specification.label or specification.field_key,
        description=description,
        data_type=data_type,
        category=FilterFieldCategory.ANNOTATION,
        column=specification.analytical_column,
        # Values arrive from an external resource; the platform records them and
        # computes nothing, so the origin is never ``computed``.
        origin=FilterFieldOrigin.IMPORTED,
        missing_semantics=specification.missing_semantics,
        allowed_values=specification.allowed_values,
        high_cardinality=specification.high_cardinality,
        searchable=specification.high_cardinality,
        sortable=specification.sortable,
        filterable=(
            specification.filterable
            and specification.value_type is not AnnotationValueType.JSON
        ),
        scientific_category=specification.scientific_category,
        semantics_column=f"{specification.analytical_column}_semantics",
        available=resource.is_usable,
        metadata={
            "annotation_resource_id": resource.id,
            "annotation_resource_key": resource.resource_key,
            "annotation_resource_version": resource.version,
            "annotation_resource_category": resource.category.value,
            "annotation_field_key": specification.field_key,
            "annotation_schema_version": resource.schema_version,
            "provider": resource.provider,
            "genome_assembly": resource.genome_assembly,
            "unit": specification.unit,
        },
    )


def annotation_field_definitions(
    resources: tuple[AnnotationResourceRecord, ...],
) -> tuple[FilterFieldDefinition, ...]:
    """Field definitions for the given resource versions.

    When several versions of one resource declare the same field, the newest
    usable version wins the dictionary entry — one identifier, one declaration —
    while every stored value keeps its own resource version.
    """

    chosen: dict[str, tuple[AnnotationResourceRecord, AnnotationFieldSpec]] = {}
    ordered = sorted(
        resources,
        key=lambda resource: (
            resource.is_usable,
            resource.released_at.timestamp() if resource.released_at else 0.0,
            resource.version,
        ),
    )
    for resource in ordered:
        for specification in resource.fields:
            chosen[annotation_field_id(resource.resource_key, specification.field_key)] = (
                resource,
                specification,
            )
    return tuple(
        annotation_field_definition(resource, specification)
        for resource, specification in chosen.values()
    )


def extend_registry(
    registry: FilterFieldRegistry,
    resources: tuple[AnnotationResourceRecord, ...],
    *,
    unavailable_field_ids: frozenset[str] = frozenset(),
) -> FilterFieldRegistry:
    """The shipped dictionary plus registered annotation fields.

    Shipped definitions always win a collision: a registered resource can add to
    the dictionary, never redefine what the platform already declares.
    """

    existing = set(registry.field_ids)
    additions = tuple(
        replace(definition, available=False)
        if definition.id in unavailable_field_ids
        else definition
        for definition in annotation_field_definitions(resources)
        if definition.id not in existing
    )
    if not additions:
        return registry
    # The dictionary version has to move when its content does: an execution
    # records the version it was validated against, and two different field sets
    # must never be able to claim the same version.
    digest = hashlib.sha256(
        "\n".join(
            f"{definition.id}:{definition.metadata.get('annotation_resource_version')}"
            f":{definition.data_type.value}:{definition.available}"
            for definition in additions
        ).encode()
    ).hexdigest()[:12]
    return FilterFieldRegistry(
        version=f"{registry.version}+annotation.{digest}",
        definitions=registry.definitions + additions,
    )


__all__ = [
    "ANNOTATION_FIELD_PREFIX",
    "annotation_field_definition",
    "annotation_field_definitions",
    "annotation_field_id",
    "extend_registry",
]
