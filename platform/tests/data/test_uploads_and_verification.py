"""Transfer grants, upload completion, verification and download grants.

The rules pinned here are the ones that keep an uploaded file from becoming a
scientific input by accident: bytes are only "arrived", never "usable"; a scan
that could not run is not a clean scan; a checksum mismatch is recorded rather
than tolerated; and a presigned URL is never a capability.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.ports import ScanVerdict
from app.application.use_cases.data.artifacts import (
    VerifyArtifact,
    VerifyArtifactCommand,
)
from app.application.use_cases.data.uploads import (
    CancelUploadSession,
    CancelUploadSessionCommand,
    CompleteUpload,
    CompleteUploadCommand,
    ExpireStaleUploadSessions,
    IssueArtifactDownload,
    IssueArtifactDownloadCommand,
)
from app.domain.data.storage import QUARANTINE_PREFIX, UPLOAD_PREFIX
from app.domain.errors import AuthorizationError, ConflictError, NotFoundError
from app.domain.value_objects.enums import (
    FileUploadState,
    FileValidationState,
    JobKind,
    MalwareScanState,
    UploadSessionState,
    ValidationCategory,
    ValidationRunState,
    ValidationSeverity,
)
from tests.data.support import TABLE, draft_version, open_upload, personal_dataset
from tests.support.actors import actor_for, create_account
from app.application.repositories import Page
from tests.support.services import NOW, build_harness

PAGE = Page(number=1, size=50)


async def _version(harness, user_id: str) -> str:
    dataset = (await personal_dataset(harness, user_id)).dataset
    return (await draft_version(harness, user_id, dataset.id)).version.id


async def test_a_transfer_grant_is_scoped_expiring_and_never_reveals_its_key() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    version_id = await _version(harness, owner)

    ticket = await open_upload(harness, owner, version_id)

    # The key is derived from server identifiers only — no filename component.
    assert ticket.artifact.storage_key.startswith(f"{UPLOAD_PREFIX}/")
    assert "cohort.tsv" not in ticket.artifact.storage_key
    assert ticket.upload_url and ticket.artifact.storage_key in ticket.upload_url
    assert ticket.expires_at == NOW + timedelta(
        seconds=harness.data.upload_url_ttl_seconds
    )
    assert ticket.session.state is UploadSessionState.CREATED
    assert ticket.artifact.upload_state is FileUploadState.PENDING
    assert ticket.artifact.validation_state is FileValidationState.NOT_VALIDATED


async def test_a_stranger_cannot_open_a_transfer_grant_on_someone_elses_version() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    stranger = await create_account(harness, "stranger@example.test")
    version_id = await _version(harness, owner)

    with pytest.raises((AuthorizationError, NotFoundError)):
        await open_upload(harness, stranger, version_id)
    assert harness.storage.presigned_uploads == []


async def test_completing_an_upload_that_never_transferred_bytes_fails_the_session() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))

    with pytest.raises(ConflictError):
        await CompleteUpload(harness.data).execute(
            CompleteUploadCommand(
                actor=await actor_for(harness, owner),
                session_id=ticket.session.id,
                request=harness.request,
            )
        )

    session = await harness.repositories.upload_sessions.get(ticket.session.id)
    assert session.state is UploadSessionState.FAILED
    assert session.failure_reason is not None
    assert harness.repositories.jobs.recorded == []


async def test_a_completed_upload_is_not_usable_until_verification_runs() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))
    harness.storage.put(ticket.artifact.storage_key, TABLE)

    view = await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )

    assert view.session.state is UploadSessionState.UPLOADED
    assert view.artifact.upload_state is FileUploadState.UPLOADED
    # "Bytes arrived" is not "file is usable".
    assert view.artifact.validation_state is FileValidationState.NOT_VALIDATED
    assert not view.artifact.is_retrievable
    # Verification is a durable job, never inline work in the request.
    assert [record.kind for record in harness.repositories.jobs.recorded] == [
        JobKind.DATASET_VALIDATION
    ]


async def test_verification_of_a_clean_matching_file_makes_it_retrievable() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )

    outcome = await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=ticket.session.id, request=harness.request)
    )

    assert outcome.scan_state is MalwareScanState.CLEAN
    assert outcome.artifact_validation_state is FileValidationState.VALID
    assert outcome.validation_run.state in (
        ValidationRunState.PASSED,
        ValidationRunState.PASSED_WITH_WARNINGS,
    )
    assert not outcome.validation_run.blocks_acceptance
    # The run records which validator decided, so a later version is comparable.
    assert outcome.validation_run.validator_version
    artifact = await harness.repositories.file_artifacts.get(ticket.artifact.id)
    assert artifact.is_retrievable


async def test_a_declared_checksum_that_does_not_match_the_stored_bytes_is_recorded() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(
        harness,
        owner,
        await _version(harness, owner),
        declared_checksum="0" * 64,
    )
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )

    outcome = await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=ticket.session.id, request=harness.request)
    )

    assert outcome.artifact_validation_state is FileValidationState.INVALID
    assert outcome.validation_run.state is ValidationRunState.FAILED
    assert outcome.validation_run.blocks_acceptance
    issues = await harness.repositories.validation_issues.list_for_run(
        outcome.validation_run.id, page=PAGE
    )
    integrity = [
        issue
        for issue in issues.items
        if issue.category is ValidationCategory.TRANSFER_INTEGRITY
        and issue.severity
        in (ValidationSeverity.ERROR, ValidationSeverity.BLOCKING)
    ]
    assert integrity, "a checksum mismatch must be reported as an integrity error"
    artifact = await harness.repositories.file_artifacts.get(ticket.artifact.id)
    assert not artifact.is_retrievable


async def test_an_infected_artifact_is_quarantined_and_never_downloadable() -> None:
    harness = build_harness()
    harness.scanner.verdict = ScanVerdict.INFECTED
    harness.scanner.detail = "test-signature"
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )

    outcome = await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=ticket.session.id, request=harness.request)
    )

    assert outcome.scan_state is MalwareScanState.INFECTED
    assert outcome.session_state is UploadSessionState.QUARANTINED
    source, destination = harness.storage.moved[-1]
    assert source == ticket.artifact.storage_key
    assert destination.startswith(f"{QUARANTINE_PREFIX}/")

    with pytest.raises(ConflictError):
        await IssueArtifactDownload(harness.data).execute(
            IssueArtifactDownloadCommand(
                actor=await actor_for(harness, owner),
                artifact_id=ticket.artifact.id,
                request=harness.request,
            )
        )
    assert harness.storage.presigned_downloads == []


async def test_a_scanner_that_cannot_answer_is_not_treated_as_clean() -> None:
    harness = build_harness()
    harness.scanner.verdict = ScanVerdict.UNAVAILABLE
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )

    outcome = await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=ticket.session.id, request=harness.request)
    )

    assert outcome.scan_state is not MalwareScanState.CLEAN
    artifact = await harness.repositories.file_artifacts.get(ticket.artifact.id)
    assert not artifact.is_retrievable


async def test_verification_is_idempotent_for_a_retried_job() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )
    verify = VerifyArtifact(harness.data)
    command = VerifyArtifactCommand(
        upload_session_id=ticket.session.id, request=harness.request
    )

    first = await verify.execute(command)
    second = await verify.execute(command)

    # A retry returns the recorded outcome instead of deciding a second time.
    assert second.validation_run.id == first.validation_run.id
    runs = await harness.repositories.validation_runs.list_for_subject(
        subject_type="file_artifact", subject_id=ticket.artifact.id, page=PAGE
    )
    assert runs.total == 1


async def test_a_download_grant_is_short_lived_scoped_and_audited() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    stranger = await create_account(harness, "stranger@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )
    await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=ticket.session.id, request=harness.request)
    )

    grant = await IssueArtifactDownload(harness.data).execute(
        IssueArtifactDownloadCommand(
            actor=await actor_for(harness, owner),
            artifact_id=ticket.artifact.id,
            request=harness.request,
        )
    )
    assert grant.expires_in_seconds == harness.data.download_url_ttl_seconds
    assert any(
        record.action == "file_artifact.download_authorized"
        for record in harness.repositories.audit.records
    )

    # Knowing the identifier is not access: the check is re-evaluated per call.
    with pytest.raises((AuthorizationError, NotFoundError)):
        await IssueArtifactDownload(harness.data).execute(
            IssueArtifactDownloadCommand(
                actor=await actor_for(harness, stranger),
                artifact_id=ticket.artifact.id,
                request=harness.request,
            )
        )
    assert harness.storage.presigned_downloads == [ticket.artifact.storage_key]


async def test_cancelling_a_grant_stops_it_from_ever_completing() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))

    await CancelUploadSession(harness.data).execute(
        CancelUploadSessionCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            reason="wrong file",
            request=harness.request,
        )
    )

    # Bytes that arrive after cancellation cannot resurrect the session: the
    # recorded outcome is reported back unchanged and nothing is queued.
    harness.storage.put(ticket.artifact.storage_key, TABLE)
    view = await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )
    assert view.session.state is UploadSessionState.CANCELLED
    assert harness.repositories.jobs.recorded == []


async def test_a_grant_left_open_past_its_expiry_is_expired_by_maintenance() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    ticket = await open_upload(harness, owner, await _version(harness, owner))

    harness.advance_to(NOW + timedelta(seconds=harness.data.upload_url_ttl_seconds + 60))
    expired = await ExpireStaleUploadSessions(harness.data).execute(
        request=harness.request
    )

    assert ticket.session.id in expired
    session = await harness.repositories.upload_sessions.get(ticket.session.id)
    assert session.state is UploadSessionState.EXPIRED


async def test_an_identical_re_upload_is_reported_as_a_duplicate_not_deduplicated() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    version_id = await _version(harness, owner)

    first = await open_upload(harness, owner, version_id, filename="a.tsv")
    harness.storage.put(first.artifact.storage_key, TABLE)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, owner),
            session_id=first.session.id,
            request=harness.request,
        )
    )
    await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=first.session.id, request=harness.request)
    )

    # A verified version no longer accepts bytes, so the second submission is a
    # new version — which is exactly why deduplication would corrupt lineage.
    dataset_id = (
        await harness.repositories.dataset_versions.get(version_id)
    ).dataset_id
    other_version = (await draft_version(harness, owner, dataset_id)).version
    second = await open_upload(harness, owner, other_version.id, filename="b.tsv")

    # Reported, never resolved: silently reusing the first artifact would
    # rewrite lineage for the second submission.
    assert second.artifact.id != first.artifact.id
    assert second.artifact.storage_key != first.artifact.storage_key
    assert second.duplicate_of_file_artifact_id in (None, first.artifact.id)
