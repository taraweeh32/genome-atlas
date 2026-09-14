"""Ingestion, versioning, conflict preservation, provenance and tenant isolation.

The behaviour these tests pin down is the part that would silently corrupt science
if it regressed: evidence is never overwritten, disagreement is never resolved,
values are never repaired, and nothing here classifies anything.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.evidence.records import (
    EvidenceRecords,
    ListEvidenceQuery,
    RecordEvidenceCommand,
    WithdrawEvidenceCommand,
)
from app.domain.errors import AuthorizationError, NotFoundError, ValidationError
from app.domain.value_objects.enums import (
    CriterionDirection,
    DataOrigin,
    EvidenceCategory,
    EvidenceConflictKind,
    EvidenceIngestionState,
    EvidenceRecordState,
    EvidenceSourceCategory,
    EvidenceStrength,
    ScientificResourceState,
)
from tests.evidence.support import (
    OTHER_SOURCE_KEY,
    PAGE,
    RETRIEVED_AT,
    SOURCE_KEY,
    SOURCE_VERSION,
    activate_source,
    claim,
    evidence_payload,
    ingest,
    platform_admin,
    registered_source,
)
from tests.results.support import execution_for, ingest_variants, normalized_claim
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def arrange(harness=None):
    """An active source, a curator with a workspace, and one real variant."""
    harness = harness or build_harness()
    admin_id = await platform_admin(harness)
    source = await registered_source(harness, admin_id)
    _, execution, dataset_version_id = await execution_for(harness, admin_id)
    await ingest_variants(
        harness,
        admin_id,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )
    variants = await harness.repositories.variants.list_for_dataset_version(
        dataset_version_id, page=PAGE
    )
    actor = await actor_for(harness, admin_id)
    return harness, admin_id, source, variants.items[0], next(iter(actor.workspaces))


# --------------------------------------------------------------------------- #
# Storing what a source stated                                               #
# --------------------------------------------------------------------------- #


async def test_ingestion_stores_claims_with_source_identity_origin_and_provenance():
    harness, admin_id, _source, variant, workspace_id = await arrange()

    outcome = await ingest(
        harness,
        evidence_payload(claims=(claim(variant_id=variant.id),)),
        workspace_id=workspace_id,
        actor=await actor_for(harness, admin_id),
    )

    assert outcome.batch.state is EvidenceIngestionState.ACCEPTED
    assert outcome.batch.stored_record_count == 1
    (record,) = outcome.stored
    assert record.variant_id == variant.id
    # Identity travels with the record: which source, which version, which release,
    # when retrieved, and how it arrived.
    assert (record.source_key, record.source_version) == (SOURCE_KEY, SOURCE_VERSION)
    assert record.source_identifier == "FIXTURE:1"
    assert record.retrieved_at == RETRIEVED_AT
    assert record.origin is DataOrigin.RETRIEVED
    assert record.version_number == 1
    assert record.provenance["source_release_label"] == "fixture-release-1"
    assert record.provenance["source_checksum_value"] == "0" * 64
    assert record.provenance["is_development_payload"] is True
    # The source's own values are kept verbatim.
    assert record.payload == {"fixture_field": "fixture_value"}


async def test_a_variant_the_platform_cannot_resolve_is_recorded_not_guessed():
    harness, admin_id, _source, _variant, workspace_id = await arrange()

    outcome = await ingest(
        harness,
        evidence_payload(claims=(claim(variant_identifier="not-a-known-variant"),)),
        workspace_id=workspace_id,
        actor=await actor_for(harness, admin_id),
    )

    assert outcome.stored == ()
    assert outcome.batch.rejected_record_count == 1
    assert outcome.batch.state is EvidenceIngestionState.REJECTED
    assert [finding.code for finding in outcome.findings] == [
        "evidence.variant_unresolved"
    ]


async def test_a_category_the_source_never_declared_is_refused_not_repaired():
    harness, admin_id, _source, variant, workspace_id = await arrange()

    outcome = await ingest(
        harness,
        evidence_payload(
            claims=(
                claim(variant_id=variant.id, category=EvidenceCategory.SEGREGATION),
            )
        ),
        workspace_id=workspace_id,
        actor=await actor_for(harness, admin_id),
    )

    assert outcome.stored == ()
    assert "evidence.category_not_declared" in {f.code for f in outcome.findings}


async def test_a_strength_a_source_does_not_state_is_never_attributed_to_it():
    """A population resource supplies frequencies, not weights."""
    harness = build_harness()
    admin_id = await platform_admin(harness)
    _source = await registered_source(
        harness,
        admin_id,
        source_key="fixture-population",
        category=EvidenceSourceCategory.POPULATION,
        supplies=(EvidenceCategory.POPULATION,),
        supplies_strength=False,
    )
    _, execution, dataset_version_id = await execution_for(harness, admin_id)
    await ingest_variants(
        harness,
        admin_id,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )
    variants = await harness.repositories.variants.list_for_dataset_version(
        dataset_version_id, page=PAGE
    )

    outcome = await ingest(
        harness,
        evidence_payload(
            source_key="fixture-population",
            claims=(
                claim(
                    variant_id=variants.items[0].id,
                    category=EvidenceCategory.POPULATION,
                    strength=EvidenceStrength.STRONG,
                    direction=CriterionDirection.BENIGN,
                ),
            ),
        ),
    )

    assert outcome.stored == ()
    assert "evidence.strength_not_supplied_by_source" in {
        f.code for f in outcome.findings
    }


async def test_a_delivery_naming_an_unregistered_source_version_stores_nothing():
    """An unknown release is refused outright; it is never treated as the known one."""
    harness, _admin_id, _source, variant, _workspace_id = await arrange()

    with pytest.raises(NotFoundError):
        await ingest(harness, _mismatched_payload(variant))

    stored = await harness.repositories.evidence_records.list_records(page=PAGE)
    assert stored.total == 0


def _mismatched_payload(variant):
    """A payload whose declared release contradicts the identity it names."""
    payload = evidence_payload(claims=(claim(variant_id=variant.id),))
    from dataclasses import replace

    return replace(
        payload, source=replace(payload.source, version="0.0.1-development-only")
    )


async def test_a_delivery_from_an_unusable_source_version_stores_nothing():
    harness, admin_id, source, variant, _workspace_id = await arrange()
    await activate_source(
        harness, admin_id, source.id, state=ScientificResourceState.RETIRED
    )

    with pytest.raises(ValidationError):
        await ingest(harness, evidence_payload(claims=(claim(variant_id=variant.id),)))


# --------------------------------------------------------------------------- #
# Versioning and idempotency                                                  #
# --------------------------------------------------------------------------- #


async def test_a_later_delivery_of_the_same_statement_creates_a_new_version():
    harness, _admin_id, _source, variant, _workspace_id = await arrange()
    first = await ingest(
        harness, evidence_payload(claims=(claim(variant_id=variant.id),))
    )

    second = await ingest(
        harness,
        evidence_payload(
            claims=(
                claim(
                    variant_id=variant.id,
                    summary="fixture assertion, restated differently",
                ),
            )
        ),
    )

    (new_record,) = second.stored
    assert new_record.version_number == 2
    assert new_record.supersedes_id == first.stored[0].id
    previous = await harness.repositories.evidence_records.get(first.stored[0].id)
    # The earlier version keeps its own content and stays readable, so an
    # interpretation that cited it remains reproducible.
    assert previous.state is EvidenceRecordState.SUPERSEDED
    assert previous.superseded_by_id == new_record.id
    assert previous.summary == "fixture assertion, not a real clinical assertion"


async def test_redelivering_an_identical_payload_writes_nothing_twice():
    harness, _admin_id, _source, variant, _workspace_id = await arrange()
    payload = evidence_payload(claims=(claim(variant_id=variant.id),))
    first = await ingest(harness, payload)

    again = await ingest(harness, payload)

    assert again.was_redelivery is True
    assert again.batch.id == first.batch.id
    assert again.stored == ()
    stored = await harness.repositories.evidence_records.list_records(page=PAGE)
    assert stored.total == 1


async def test_the_same_claim_twice_in_one_delivery_is_stored_once():
    harness, _admin_id, _source, variant, _workspace_id = await arrange()

    outcome = await ingest(
        harness,
        evidence_payload(
            claims=(claim(variant_id=variant.id), claim(variant_id=variant.id))
        ),
    )

    assert len(outcome.stored) == 1
    assert outcome.batch.duplicate_record_count == 1


# --------------------------------------------------------------------------- #
# Disagreement                                                                #
# --------------------------------------------------------------------------- #


async def test_two_sources_that_disagree_are_both_kept_and_the_conflict_reported():
    harness, admin_id, _source, variant, _workspace_id = await arrange()
    await registered_source(harness, admin_id, source_key=OTHER_SOURCE_KEY)
    actor = await actor_for(harness, admin_id)

    pathogenic = await ingest(
        harness,
        evidence_payload(
            claims=(claim(variant_id=variant.id, direction=CriterionDirection.PATHOGENIC),)
        ),
    )
    benign = await ingest(
        harness,
        evidence_payload(
            source_key=OTHER_SOURCE_KEY,
            claims=(claim(variant_id=variant.id, direction=CriterionDirection.BENIGN),),
        ),
    )

    # Neither source overwrote the other.
    assert pathogenic.stored[0].state is EvidenceRecordState.AVAILABLE
    assert benign.stored[0].state is EvidenceRecordState.AVAILABLE
    conflicts = await EvidenceRecords(harness.evidence).conflicts(
        actor, harness.request, variant_id=variant.id
    )
    kinds = {conflict.kind for conflict in conflicts}
    assert EvidenceConflictKind.DIRECTION in kinds
    direction = next(c for c in conflicts if c.kind is EvidenceConflictKind.DIRECTION)
    assert set(direction.source_keys) == {SOURCE_KEY, OTHER_SOURCE_KEY}
    assert set(direction.evidence_ids) == {
        pathogenic.stored[0].id,
        benign.stored[0].id,
    }


async def test_a_superseded_version_is_history_not_a_live_disagreement():
    harness, admin_id, _source, variant, _workspace_id = await arrange()
    actor = await actor_for(harness, admin_id)
    await ingest(
        harness,
        evidence_payload(
            claims=(claim(variant_id=variant.id, direction=CriterionDirection.PATHOGENIC),)
        ),
    )
    await ingest(
        harness,
        evidence_payload(
            claims=(claim(variant_id=variant.id, direction=CriterionDirection.BENIGN),)
        ),
    )

    conflicts = await EvidenceRecords(harness.evidence).conflicts(
        actor, harness.request, variant_id=variant.id
    )
    history = await EvidenceRecords(harness.evidence).history(
        actor, harness.request, variant_id=variant.id
    )

    # One source changing its mind is a new version, not a conflict with itself.
    assert conflicts == ()
    assert len(history) == 2
    assert {record.version_number for record in history} == {1, 2}


# --------------------------------------------------------------------------- #
# Curation, withdrawal, isolation                                             #
# --------------------------------------------------------------------------- #


async def test_curated_evidence_is_attributable_and_never_looks_like_a_source_delivery():
    harness, admin_id, _source, variant, workspace_id = await arrange()
    records = EvidenceRecords(harness.evidence)

    stored = await records.record(
        RecordEvidenceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            variant_id=variant.id,
            category=EvidenceCategory.FUNCTIONAL,
            source_key=SOURCE_KEY,
            source_version=SOURCE_VERSION,
            workspace_id=workspace_id,
            direction=CriterionDirection.PATHOGENIC,
            strength=EvidenceStrength.SUPPORTING,
            rationale="fixture rationale entered by a person",
        )
    )

    assert stored.origin is DataOrigin.HUMAN_ENTERED
    assert stored.created_by == admin_id
    assert stored.ingestion_batch_id is None
    assert stored.provenance["curated_by"] == admin_id


async def test_withdrawing_evidence_keeps_its_content_and_records_the_reason():
    harness, admin_id, _source, variant, workspace_id = await arrange()
    outcome = await ingest(
        harness,
        evidence_payload(claims=(claim(variant_id=variant.id),)),
        workspace_id=workspace_id,
        actor=await actor_for(harness, admin_id),
    )
    records = EvidenceRecords(harness.evidence)

    withdrawn = await records.withdraw(
        WithdrawEvidenceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            evidence_id=outcome.stored[0].id,
            reason="withdrawn by the fixture source",
        )
    )

    assert withdrawn.state is EvidenceRecordState.WITHDRAWN
    assert withdrawn.payload == {"fixture_field": "fixture_value"}
    assert withdrawn.provenance["withdrawal_reason"] == "withdrawn by the fixture source"
    assert withdrawn.is_current is False


async def test_another_tenant_can_neither_list_nor_read_workspace_evidence():
    harness, admin_id, _source, variant, workspace_id = await arrange()
    outcome = await ingest(
        harness,
        evidence_payload(claims=(claim(variant_id=variant.id),)),
        workspace_id=workspace_id,
        actor=await actor_for(harness, admin_id),
    )
    outsider_id = await create_account(harness, "outsider@example.org")
    outsider = await actor_for(harness, outsider_id)
    records = EvidenceRecords(harness.evidence)

    listed = await records.list(
        ListEvidenceQuery(
            actor=outsider,
            request=harness.request,
            page=PAGE,
            # A known workspace identifier in the request buys nothing: scope is
            # built from the caller's own grants.
            workspace_id=workspace_id,
        )
    )
    assert listed.total == 0

    with pytest.raises(AuthorizationError):
        await records.get(outsider, harness.request, outcome.stored[0].id)
