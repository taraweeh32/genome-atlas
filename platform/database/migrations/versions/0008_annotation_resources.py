"""Annotation resource fields, annotation profiles, runs, results and findings.

Additive revision on top of Packages 2-7.

Deliberately *not* created here:

* an annotation resource table — a registered annotation resource version is a
  row in the existing ``app.scientific_resources`` registry (kind
  ``annotation_resource``), so it inherits the platform's resource lifecycle;
* an annotation value table — annotation values are ``app.variant_annotations``
  rows from Package 6, and a second annotation-row model would split the data.

New tables:

* ``app.annotation_resource_fields`` — the fields a resource version declares it
  produces. This is the schema ingestion validates against and the source of the
  filterable annotation fields Package 7 consumes, which is why a new annotation
  field is a row and never a migration.
* ``app.annotation_profiles`` / ``app.annotation_profile_versions`` — immutable
  configuration: pinned resource versions, reference context, capability,
  parameters and configuration digest.
* ``app.annotation_runs`` — the application's workflow record for one run, with
  the configuration frozen at request time and the identities the compute
  subsystem reported.
* ``app.annotation_result_versions`` — the versioned annotation result. Unique per
  (run, resource key, version number), so an updated resource version adds a
  version and nothing is overwritten; a superseded version stays readable.
* ``app.annotation_validation_findings`` — recorded validation observations, so a
  rejected record stays explainable after the request is gone.

The ``platform.jobs.kind`` and ``platform.scheduled_jobs.job_kind`` check
constraints are re-issued against the extended ``JobKind`` vocabulary, which now
includes the two annotation job kinds. Existing rows are unaffected: the value set
only grows.

Revision ID: 0008_annotation_resources
Revises: 0007_filtering_ranking
"""

from __future__ import annotations

from alembic import op

from app.domain.value_objects.enums import JobKind
from app.infrastructure.persistence.models import Base

revision = "0008_annotation_resources"
down_revision = "0007_filtering_ranking"
branch_labels = None
depends_on = None

#: The exact table set this revision creates, as ``schema.table``. Asserted
#: against ``Base.metadata`` by the schema-integrity test.
TABLES: tuple[str, ...] = (
    "app.annotation_resource_fields",
    "app.annotation_profiles",
    "app.annotation_profile_versions",
    "app.annotation_runs",
    "app.annotation_result_versions",
    "app.annotation_validation_findings",
)

_APP = "app"
_PLATFORM = "platform"

#: Job-kind check constraints that derive from the vocabulary and therefore have
#: to be re-issued whenever it grows.
_JOB_KIND_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "kind", "kind_valid"),
    ("scheduled_jobs", "job_kind", "job_kind_valid"),
)


def _vocabulary(vocabulary) -> str:  # noqa: ANN001 - StrEnum subclass
    return ", ".join(f"'{member.value}'" for member in vocabulary)


def _replace_job_kind_checks() -> None:
    values = _vocabulary(JobKind)
    for table, column, constraint in _JOB_KIND_CHECKS:
        op.execute(
            f"ALTER TABLE {_PLATFORM}.{table} DROP CONSTRAINT ck_{table}_{constraint}"
        )
        op.execute(
            f"ALTER TABLE {_PLATFORM}.{table} ADD CONSTRAINT ck_{table}_{constraint} "
            f"CHECK ({column} IN ({values}))"
        )


def _owned_tables() -> list:
    owned = set(TABLES)
    return [
        table
        for table in Base.metadata.sorted_tables
        if f"{table.schema or _APP}.{table.name}" in owned
    ]


def upgrade() -> None:
    connection = op.get_bind()
    Base.metadata.create_all(bind=connection, tables=_owned_tables(), checkfirst=False)
    _replace_job_kind_checks()


def downgrade() -> None:
    connection = op.get_bind()
    Base.metadata.drop_all(
        bind=connection, tables=list(reversed(_owned_tables())), checkfirst=False
    )
    _replace_job_kind_checks()
