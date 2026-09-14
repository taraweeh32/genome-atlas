"""Shared arrangement for the Package 8 tests.

Nothing here performs annotation. Every payload is a *fixture-declared claim*,
exactly as an external scientific tool would have declared it, and every payload
is marked ``is_development_payload=True`` so nothing arranged here can be
mistaken for a scientific result.
"""

from __future__ import annotations

from app.application.repositories import Page
from app.application.use_cases.annotation.ingestion import (
    IngestAnnotationCommand,
    IngestAnnotationPayload,
)
from app.application.use_cases.annotation.profiles import (
    AnnotationProfileService,
    CreateProfileCommand,
    ProfileVersionInput,
)
from app.application.use_cases.annotation.resources import (
    RegisterAnnotationResource,
    RegisterResourceCommand,
)
from app.application.use_cases.annotation.runs import (
    RequestAnnotationRun,
    RequestRunCommand,
)
from app.domain.annotation.entities import AnnotationFieldSpec
from app.domain.value_objects.enums import (
    DataOrigin,
    AnnotationResourceCategory,
    AnnotationValueType,
    PlatformRole,
    ValueSemantics,
)
from app.scientific.annotation import (
    ANNOTATION_CONTRACT_VERSION,
    AnnotationFieldValueClaim,
    AnnotationPayload,
    AnnotationRecordClaim,
    AnnotationResourceIdentity,
)
from tests.support.actors import actor_for, create_account, grant_platform_role

PAGE = Page(number=1, size=25)

#: DEVELOPMENT ONLY identifiers. They name a fixture, not a scientific resource.
RESOURCE_KEY = "fixture-annotation-source"
RESOURCE_VERSION = "0.0.0-development-only"
GENOME = "GRCh38"
CAPABILITY = "integration.echo"

FIELDS = (
    AnnotationFieldSpec(
        field_key="fixture_consequence",
        label="Fixture consequence",
        value_type=AnnotationValueType.STRING,
        scientific_category="consequence",
    ),
    AnnotationFieldSpec(
        field_key="fixture_score",
        label="Fixture score",
        value_type=AnnotationValueType.NUMBER,
        scientific_category="functional",
    ),
)


async def platform_admin(harness, email: str = "admin@example.org") -> str:
    user_id = await create_account(harness, email, display_name="Platform Admin")
    await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    return user_id


async def registered_resource(
    harness,
    admin_id: str,
    *,
    version: str = RESOURCE_VERSION,
    resource_key: str = RESOURCE_KEY,
    genome_assembly: str | None = GENOME,
    fields: tuple[AnnotationFieldSpec, ...] = FIELDS,
    category: AnnotationResourceCategory = AnnotationResourceCategory.CONSEQUENCE,
):
    return await RegisterAnnotationResource(harness.annotation).execute(
        RegisterResourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            resource_key=resource_key,
            version=version,
            display_name=f"Fixture source {version}",
            category=category,
            provider="fixture",
            genome_assembly=genome_assembly,
            schema_version="1",
            fields=fields,
        )
    )


async def published_profile(
    harness,
    admin_id: str,
    *,
    resource_ids: tuple[str, ...],
    name: str = "Fixture profile",
    genome_assembly: str | None = GENOME,
):
    service = AnnotationProfileService(harness.annotation)
    actor = await actor_for(harness, admin_id)
    view = await service.create(
        CreateProfileCommand(
            actor=actor,
            request=harness.request,
            name=name,
            version=ProfileVersionInput(
                capability_id=CAPABILITY,
                resource_ids=resource_ids,
                genome_assembly=genome_assembly,
            ),
        )
    )
    profile = await service.publish(actor, harness.request, view.profile.id)
    return profile, await service.get(actor, harness.request, profile.id)


def value(
    field_key: str,
    *,
    string: str | None = None,
    number: float | None = None,
    value_type: AnnotationValueType | None = None,
    semantics: ValueSemantics = ValueSemantics.PRESENT,
) -> AnnotationFieldValueClaim:
    if value_type is None:
        value_type = (
            AnnotationValueType.NUMBER if number is not None or string is None
            else AnnotationValueType.STRING
        )
    return AnnotationFieldValueClaim(
        field_key=field_key,
        value_type=value_type.value,
        value_string=string,
        value_number=number,
        value_semantics=ValueSemantics(semantics).value,
    )


def annotation_payload(
    *,
    annotation_run_id: str,
    variant_id: str,
    values: tuple[AnnotationFieldValueClaim, ...] | None = None,
    resource_version: str = RESOURCE_VERSION,
    resource_key: str = RESOURCE_KEY,
    genome_assembly: str | None = GENOME,
    records: tuple[AnnotationRecordClaim, ...] | None = None,
    declared_record_count: int | None = None,
) -> AnnotationPayload:
    if records is None:
        records = (
            AnnotationRecordClaim(
                variant_id=variant_id,
                values=values
                or (value("fixture_consequence", string="fixture_term"),),
                origin=DataOrigin.RETRIEVED.value,
            ),
        )
    return AnnotationPayload(
        contract_version=ANNOTATION_CONTRACT_VERSION,
        annotation_run_id=annotation_run_id,
        resource=AnnotationResourceIdentity(
            resource_key=resource_key,
            resource_version=resource_version,
            schema_version="1",
            genome_assembly=genome_assembly,
        ),
        engine_version="0.0.0-development-only",
        scientific_execution_id="sci-exec-annotation-1",
        genome_assembly=genome_assembly,
        records=records,
        declared_record_count=declared_record_count,
        is_development_payload=True,
    )


async def ingest(harness, payload: AnnotationPayload):
    return await IngestAnnotationPayload(harness.annotation).execute(
        IngestAnnotationCommand(request=harness.request, payload=payload)
    )


async def requested_run(
    harness,
    user_id: str,
    *,
    profile_id: str,
    result_set_id: str,
    idempotency_key: str | None = None,
):
    return await RequestAnnotationRun(harness.annotation).execute(
        RequestRunCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            annotation_profile_id=profile_id,
            result_set_id=result_set_id,
            idempotency_key=idempotency_key,
        )
    )


__all__ = [
    "CAPABILITY",
    "FIELDS",
    "GENOME",
    "PAGE",
    "RESOURCE_KEY",
    "RESOURCE_VERSION",
    "annotation_payload",
    "ingest",
    "platform_admin",
    "published_profile",
    "registered_resource",
    "requested_run",
    "value",
]
