"""Shared arrangement for the dataset tests.

Each helper drives the *real* use cases rather than writing rows directly, so a
test can never arrange a state the platform itself would refuse to produce.
"""

from __future__ import annotations

from app.application.use_cases.data.datasets import (
    CreateDataset,
    CreateDatasetCommand,
    CreateDatasetVersion,
    CreateDatasetVersionCommand,
)
from app.application.use_cases.data.uploads import (
    CompleteUpload,
    CompleteUploadCommand,
    OpenUploadSession,
    OpenUploadSessionCommand,
)
from app.application.use_cases.data.artifacts import (
    VerifyArtifact,
    VerifyArtifactCommand,
)
from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    DatasetKind,
    ReferenceBuildDeclaration,
)
from tests.support.actors import actor_for
from tests.support.data_storage import checksum_of
from tests.support.services import Harness

#: A small, deliberately non-genomic tabular payload: these tests exercise file
#: handling and mapping, never scientific interpretation.
TABLE = b"chrom\tpos\tref\talt\tdepth\nchr1\t100\tA\tT\t30\nchr1\t200\tG\tC\tNA\n"


async def personal_dataset(
    harness: Harness,
    user_id: str,
    *,
    name: str = "Cohort Table",
    kind: DatasetKind = DatasetKind.VARIANT_CALLS,
):
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    return await CreateDataset(harness.data).execute(
        CreateDatasetCommand(
            actor=await actor_for(harness, user_id),
            workspace_id=workspace.id,
            project_id=None,
            name=name,
            kind=kind,
            description=None,
            reference_build_declared=ReferenceBuildDeclaration.GRCH38,
            request=harness.request,
        )
    )


async def draft_version(harness: Harness, user_id: str, dataset_id: str):
    return await CreateDatasetVersion(harness.data).execute(
        CreateDatasetVersionCommand(
            actor=await actor_for(harness, user_id),
            dataset_id=dataset_id,
            notes=None,
            reference_build_declared=None,
            request=harness.request,
        )
    )


async def open_upload(
    harness: Harness,
    user_id: str,
    version_id: str,
    *,
    filename: str = "cohort.tsv",
    payload: bytes = TABLE,
    declared_size: int | None = None,
    declared_checksum: str | None = None,
):
    return await OpenUploadSession(harness.data).execute(
        OpenUploadSessionCommand(
            actor=await actor_for(harness, user_id),
            version_id=version_id,
            filename=filename,
            size_bytes=declared_size if declared_size is not None else len(payload),
            declared_format=None,
            checksum_algorithm=ChecksumAlgorithm.SHA256,
            checksum_value=(
                declared_checksum
                if declared_checksum is not None
                else checksum_of(payload)
            ),
            content_type="text/tab-separated-values",
            request=harness.request,
        )
    )


async def uploaded_artifact(
    harness: Harness,
    user_id: str,
    version_id: str,
    *,
    filename: str = "cohort.tsv",
    payload: bytes = TABLE,
):
    """Open a grant, transfer the bytes, complete, then run verification."""
    ticket = await open_upload(
        harness, user_id, version_id, filename=filename, payload=payload
    )
    harness.storage.put(ticket.artifact.storage_key, payload)
    await CompleteUpload(harness.data).execute(
        CompleteUploadCommand(
            actor=await actor_for(harness, user_id),
            session_id=ticket.session.id,
            request=harness.request,
        )
    )
    outcome = await VerifyArtifact(harness.data).execute(
        VerifyArtifactCommand(upload_session_id=ticket.session.id, request=harness.request)
    )
    artifact = await harness.repositories.file_artifacts.get(ticket.artifact.id)
    return ticket, artifact, outcome


__all__ = [
    "TABLE",
    "draft_version",
    "open_upload",
    "personal_dataset",
    "uploaded_artifact",
]
