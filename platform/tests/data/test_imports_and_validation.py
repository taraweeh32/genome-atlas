"""Import sessions, column mapping and structural validation.

The rules pinned here are the ones that keep meaning from being invented: a
suggested mapping is not a confirmed one, an import never runs on a guess, an
absent value is never read as zero, and a passing import never accepts a version
on a human's behalf.
"""

from __future__ import annotations

import pytest

from app.application.repositories import Page
from app.application.use_cases.data.datasets import (
    DecideDatasetVersion,
    DecideDatasetVersionCommand,
)
from app.application.use_cases.data.imports import (
    AbandonImportSession,
    AbandonImportSessionCommand,
    ColumnMappingRequest,
    ConfirmColumnMapping,
    ConfirmColumnMappingCommand,
    ExecuteImport,
    ExecuteImportCommand,
    OpenImportSession,
    OpenImportSessionCommand,
    SubmitImport,
    SubmitImportCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import (
    DatasetVersionState,
    FieldConcept,
    ImportSessionState,
    JobKind,
    MappingOrigin,
    MappingStatus,
    ValidationCategory,
    ValidationRunState,
    ValueSemantics,
)
from tests.data.support import TABLE, draft_version, personal_dataset, uploaded_artifact
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness

PAGE = Page(number=1, size=50)

#: The mapping a submitter would confirm for ``TABLE``: four coordinate columns
#: plus one numeric column carried as read depth.
CONFIRMED = (
    ColumnMappingRequest(0, "chrom", FieldConcept.CHROMOSOME),
    ColumnMappingRequest(1, "pos", FieldConcept.POSITION),
    ColumnMappingRequest(2, "ref", FieldConcept.REFERENCE_ALLELE),
    ColumnMappingRequest(3, "alt", FieldConcept.ALTERNATE_ALLELE),
    ColumnMappingRequest(4, "depth", FieldConcept.READ_DEPTH),
)


async def _verified_artifact(harness, user_id: str, *, payload: bytes = TABLE):
    dataset = (await personal_dataset(harness, user_id)).dataset
    version = (await draft_version(harness, user_id, dataset.id)).version
    _, artifact, _ = await uploaded_artifact(
        harness, user_id, version.id, payload=payload
    )
    return dataset, version, artifact


async def _open(harness, user_id: str, artifact_id: str, *, key: str | None = None):
    return await OpenImportSession(harness.data).execute(
        OpenImportSessionCommand(
            actor=await actor_for(harness, user_id),
            artifact_id=artifact_id,
            idempotency_key=key,
            request=harness.request,
        )
    )


async def test_an_import_offers_suggestions_that_are_not_yet_decisions() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)

    view = await _open(harness, owner, artifact.id)

    assert view.session.state is ImportSessionState.OPEN
    assert [mapping.source_column_name for mapping in view.mappings] == [
        "chrom",
        "pos",
        "ref",
        "alt",
        "depth",
    ]
    # Every row is a suggestion until a person confirms it.
    assert {mapping.origin for mapping in view.mappings} == {
        MappingOrigin.SYSTEM_SUGGESTED
    }
    assert view.submission_blocked_reason == "mapping_not_confirmed"
    # The inspection records how much of the object it actually looked at.
    assert view.session.import_provenance["coverage"] in (
        "bounded_prefix",
        "complete_object",
    )
    assert view.session.import_provenance["inspector_version"]


async def test_an_unverified_file_cannot_be_imported() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    dataset = (await personal_dataset(harness, owner)).dataset
    version = (await draft_version(harness, owner, dataset.id)).version
    from tests.data.support import open_upload  # local: only this test needs it

    ticket = await open_upload(harness, owner, version.id)
    harness.storage.put(ticket.artifact.storage_key, TABLE)

    with pytest.raises(ConflictError):
        await _open(harness, owner, ticket.artifact.id)


async def test_a_stranger_cannot_open_an_import_over_someone_elses_file() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    stranger = await create_account(harness, "stranger@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)

    with pytest.raises((AuthorizationError, NotFoundError)):
        await _open(harness, stranger, artifact.id)


async def test_reopening_with_the_same_idempotency_key_returns_the_same_session() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)

    first = await _open(harness, owner, artifact.id, key="client-key-1")
    second = await _open(harness, owner, artifact.id, key="client-key-1")

    assert second.session.id == first.session.id


async def test_a_mapping_missing_a_required_concept_is_refused_with_reasons() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)
    view = await _open(harness, owner, artifact.id)

    with pytest.raises(ValidationError) as raised:
        await ConfirmColumnMapping(harness.data).execute(
            ConfirmColumnMappingCommand(
                actor=await actor_for(harness, owner),
                session_id=view.session.id,
                decisions=CONFIRMED[:2],  # chromosome and position only
                request=harness.request,
            )
        )

    problems = raised.value.details["problems"]
    codes = {problem["code"] for problem in problems}
    assert "required_concept_unmapped" in codes


async def test_confirming_a_mapping_records_who_decided_it_and_keeps_it_verbatim() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)
    view = await _open(harness, owner, artifact.id)

    confirmed = await ConfirmColumnMapping(harness.data).execute(
        ConfirmColumnMappingCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            decisions=CONFIRMED,
            request=harness.request,
        )
    )

    assert {mapping.origin for mapping in confirmed.mappings} == {
        MappingOrigin.USER_SELECTED
    }
    assert all(
        mapping.status is MappingStatus.MAPPED for mapping in confirmed.mappings
    )
    assert confirmed.session.mapping_confirmed_at is not None
    # Kept verbatim alongside the rows: the configuration a person confirmed
    # survives independently of any later re-derivation.
    assert confirmed.session.mapping_metadata["confirmed_by"] == owner
    assert len(confirmed.session.mapping_metadata["columns"]) == len(CONFIRMED)
    assert confirmed.submission_blocked_reason is None


async def test_an_unconfirmed_import_cannot_be_submitted() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)
    view = await _open(harness, owner, artifact.id)

    with pytest.raises(ConflictError):
        await SubmitImport(harness.data).execute(
            SubmitImportCommand(
                actor=await actor_for(harness, owner),
                session_id=view.session.id,
                request=harness.request,
            )
        )
    assert not [
        record
        for record in harness.repositories.jobs.recorded
        if record.kind is JobKind.DATASET_IMPORT
    ]


async def test_submitting_queues_a_durable_import_job_and_freezes_the_mapping() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)
    view = await _open(harness, owner, artifact.id)
    await ConfirmColumnMapping(harness.data).execute(
        ConfirmColumnMappingCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            decisions=CONFIRMED,
            request=harness.request,
        )
    )

    submitted = await SubmitImport(harness.data).execute(
        SubmitImportCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            request=harness.request,
        )
    )

    assert submitted.session.state is ImportSessionState.SUBMITTED
    jobs = [
        record
        for record in harness.repositories.jobs.recorded
        if record.kind is JobKind.DATASET_IMPORT
    ]
    assert len(jobs) == 1
    assert jobs[0].idempotency_key == f"import-execution:{view.session.id}"
    assert jobs[0].payload["import_session_id"] == view.session.id

    # A submitted configuration is provenance: it is never edited in place.
    with pytest.raises(ConflictError):
        await ConfirmColumnMapping(harness.data).execute(
            ConfirmColumnMappingCommand(
                actor=await actor_for(harness, owner),
                session_id=view.session.id,
                decisions=CONFIRMED,
                request=harness.request,
            )
        )


async def _submitted_session(harness, owner: str, *, payload: bytes = TABLE):
    _, version, artifact = await _verified_artifact(harness, owner, payload=payload)
    view = await _open(harness, owner, artifact.id)
    await ConfirmColumnMapping(harness.data).execute(
        ConfirmColumnMappingCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            decisions=CONFIRMED,
            request=harness.request,
        )
    )
    await SubmitImport(harness.data).execute(
        SubmitImportCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            request=harness.request,
        )
    )
    return version, view.session


async def test_a_passing_import_validates_the_version_but_never_accepts_it() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    version, session = await _submitted_session(harness, owner)

    run = await ExecuteImport(harness.data).execute(
        ExecuteImportCommand(import_session_id=session.id, request=harness.request)
    )

    assert run.state in (
        ValidationRunState.PASSED,
        ValidationRunState.PASSED_WITH_WARNINGS,
    )
    stored_session = await harness.repositories.import_sessions.get(session.id)
    assert stored_session.state is ImportSessionState.ACCEPTED

    stored_version = await harness.repositories.dataset_versions.get(version.id)
    # Validated, not accepted: acceptance is a separate human decision.
    assert stored_version.state is DatasetVersionState.VALIDATED
    assert stored_version.processing_lineage["validation_run_id"] == run.id
    assert stored_version.processing_lineage["importer"]

    accepted = await DecideDatasetVersion(harness.data).execute(
        DecideDatasetVersionCommand(
            actor=await actor_for(harness, owner),
            version_id=version.id,
            accept=True,
            reason="reviewed and accepted",
            request=harness.request,
        )
    )
    assert accepted.version.state is DatasetVersionState.ACCEPTED


async def test_a_missing_value_is_reported_as_absent_and_never_read_as_zero() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    # Every depth cell is a missing marker; none of them is a depth of 0.
    payload = (
        b"chrom\tpos\tref\talt\tdepth\n"
        b"chr1\t100\tA\tT\tNA\n"
        b"chr1\t200\tG\tC\t\n"
    )
    _, session = await _submitted_session(harness, owner, payload=payload)

    run = await ExecuteImport(harness.data).execute(
        ExecuteImportCommand(import_session_id=session.id, request=harness.request)
    )
    issues = await harness.repositories.validation_issues.list_for_run(run.id, page=PAGE)

    absent = [
        issue
        for issue in issues.items
        if issue.value_semantics is not ValueSemantics.PRESENT
    ]
    assert absent, "an all-absent mapped column must be reported, not assumed"
    assert all(issue.value_semantics is not ValueSemantics.ZERO for issue in absent)


async def test_a_mapped_column_that_no_longer_exists_fails_the_import() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, version, artifact = await _verified_artifact(harness, owner)
    view = await _open(harness, owner, artifact.id)
    await ConfirmColumnMapping(harness.data).execute(
        ConfirmColumnMappingCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            decisions=CONFIRMED,
            request=harness.request,
        )
    )
    await SubmitImport(harness.data).execute(
        SubmitImportCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            request=harness.request,
        )
    )
    # The stored object is replaced with a differently-shaped table: the
    # confirmed mapping no longer describes it.
    harness.storage.put(artifact.storage_key, b"a\tb\n1\t2\n")

    run = await ExecuteImport(harness.data).execute(
        ExecuteImportCommand(import_session_id=view.session.id, request=harness.request)
    )

    assert run.state is ValidationRunState.FAILED
    assert run.blocks_acceptance
    issues = await harness.repositories.validation_issues.list_for_run(run.id, page=PAGE)
    assert any(
        issue.code == "mapped_column_missing"
        and issue.category is ValidationCategory.IMPORT_CONFIGURATION
        for issue in issues.items
    )
    stored_session = await harness.repositories.import_sessions.get(view.session.id)
    assert stored_session.state is ImportSessionState.REJECTED
    # The refused run is not adopted as the version's lineage: a rejected
    # import never contributes provenance to a scientific input.
    stored_version = await harness.repositories.dataset_versions.get(version.id)
    assert stored_version.processing_lineage.get("validation_run_id") != run.id


async def test_a_retried_execution_returns_the_recorded_outcome() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, session = await _submitted_session(harness, owner)
    execute = ExecuteImport(harness.data)
    command = ExecuteImportCommand(
        import_session_id=session.id, request=harness.request
    )

    first = await execute.execute(command)
    second = await execute.execute(command)

    assert second.id == first.id
    runs = await harness.repositories.validation_runs.list_for_subject(
        subject_type="import_session", subject_id=session.id, page=PAGE
    )
    assert runs.total == 1


async def test_abandoning_an_import_leaves_the_verified_file_untouched() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    _, _, artifact = await _verified_artifact(harness, owner)
    view = await _open(harness, owner, artifact.id)

    await AbandonImportSession(harness.data).execute(
        AbandonImportSessionCommand(
            actor=await actor_for(harness, owner),
            session_id=view.session.id,
            reason="wrong mapping",
            request=harness.request,
        )
    )

    stored_session = await harness.repositories.import_sessions.get(view.session.id)
    assert stored_session.state is ImportSessionState.ABANDONED
    stored_artifact = await harness.repositories.file_artifacts.get(artifact.id)
    assert stored_artifact.is_retrievable
    assert harness.storage.deleted == []

    # A fresh import over the same file is allowed: abandoning is not a refusal.
    again = await _open(harness, owner, artifact.id)
    assert again.session.id != view.session.id
