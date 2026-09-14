"""The permission vocabulary.

A permission is an *operation-specific capability*, never a user type and never
a role name. Roles grant permissions (see ``roles.py``); code checks
permissions, so adding a role never requires touching a call site.

Permissions are grouped by the scope they are evaluated in:

* ``PLATFORM_*`` — platform scope; only a platform role can grant these.
* ``ORGANIZATION_*`` — evaluated against one organization the actor is a member
  of. Never satisfied by membership of a different organization.
* ``WORKSPACE_*`` — evaluated against one workspace (personal or organization).
* ``PROJECT_*`` — evaluated against one project the actor is a member of.
"""

from __future__ import annotations

import enum


class Scope(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    PROJECT = "project"


class Permission(str, enum.Enum):
    """Stable permission identifiers. The value is what audit records store."""

    # --- platform scope -------------------------------------------------- #
    PLATFORM_ORGANIZATION_REVIEW = "platform.organization.review"
    PLATFORM_ORGANIZATION_APPROVE = "platform.organization.approve"
    PLATFORM_ORGANIZATION_LIFECYCLE = "platform.organization.lifecycle"
    PLATFORM_ORGANIZATION_READ_ANY = "platform.organization.read_any"
    PLATFORM_USER_READ = "platform.user.read"
    PLATFORM_USER_LIFECYCLE = "platform.user.lifecycle"
    PLATFORM_ROLE_MANAGE = "platform.role.manage"
    PLATFORM_AUDIT_READ = "platform.audit.read"
    PLATFORM_SECURITY_POLICY_MANAGE = "platform.security_policy.manage"
    #: Reconciliation of object storage against the artifact catalogue, and
    #: release of quarantined artifacts. Storage is platform infrastructure: an
    #: organization administrator may never reach it.
    PLATFORM_STORAGE_ADMINISTER = "platform.storage.administer"
    #: The durable-job control plane: inspect any tenant's jobs, cancel or
    #: requeue them, and recover stale work. Operational, never scientific.
    PLATFORM_JOB_ADMINISTER = "platform.job.administer"
    PLATFORM_JOB_READ = "platform.job.read"
    #: Compute-node registry and drain/health control. Scientific compute nodes
    #: are platform infrastructure; an organization administrator may never
    #: reach them.
    PLATFORM_COMPUTE_ADMINISTER = "platform.compute.administer"
    PLATFORM_COMPUTE_READ = "platform.compute.read"
    #: Platform-wide schedule oversight, distinct from owning one schedule.
    PLATFORM_SCHEDULE_ADMINISTER = "platform.schedule.administer"
    #: The scientific data layer's control plane: inspect result sets, artifacts
    #: and ingestion requests across tenants, and invalidate a result surface
    #: whose scientific inputs were withdrawn. It never grants the right to edit
    #: scientific content.
    PLATFORM_RESULT_ADMINISTER = "platform.result.administer"
    PLATFORM_RESULT_READ = "platform.result.read"
    #: The filter field dictionary and the ranking method registry are platform
    #: vocabularies: what may be filtered on, and which prioritization methods
    #: exist at all. An organization administrator may never change either.
    PLATFORM_FILTER_FIELD_ADMINISTER = "platform.filter_field.administer"
    PLATFORM_RANKING_METHOD_ADMINISTER = "platform.ranking_method.administer"
    #: Publishing and withdrawing platform-scoped filter and ranking presets,
    #: which are offered to every tenant.
    PLATFORM_QUERY_PRESET_ADMINISTER = "platform.query_preset.administer"
    #: Resource-governance limits on filtering and ranking (tree depth, page
    #: size, value-list size). Configuration, never per-tenant negotiation.
    PLATFORM_QUERY_LIMIT_MANAGE = "platform.query_limit.manage"
    #: The annotation resource registry and annotation execution profiles are
    #: platform scientific governance: which annotation resources exist, in which
    #: versions, and whether a version may be used at all. An organization
    #: administrator may never reach them.
    PLATFORM_ANNOTATION_RESOURCE_ADMINISTER = "platform.annotation_resource.administer"
    #: Cross-tenant read of annotation runs, result versions and validation
    #: findings for operational oversight. Never a grant over variant content.
    PLATFORM_ANNOTATION_READ = "platform.annotation.read"
    #: The evidence source registry: which evidence resources exist, in which
    #: versions, and whether a version may be used at all. Platform scientific
    #: governance; an organization administrator may never reach it.
    PLATFORM_EVIDENCE_RESOURCE_ADMINISTER = "platform.evidence_resource.administer"
    #: Cross-tenant read of evidence records, ingestion batches and findings for
    #: operational oversight. Never a grant to edit scientific content.
    PLATFORM_EVIDENCE_READ = "platform.evidence.read"
    #: The interpretation ruleset registry: which interpretation rulesets and
    #: specifications exist, in which versions, with which criteria and
    #: combination logic, and whether a version may be used at all. Platform
    #: scientific governance; an organization administrator may never reach it.
    PLATFORM_RULESET_ADMINISTER = "platform.ruleset.administer"
    #: Cross-tenant read of rulesets, automated evaluations and benchmark runs for
    #: scientific oversight. Never authority over a clinical decision.
    PLATFORM_CLASSIFICATION_READ = "platform.classification.read"
    #: Cross-tenant read of filter/ranking definitions and execution records for
    #: operational oversight. It never grants access to variant content.
    PLATFORM_QUERY_READ = "platform.query.read"

    # --- organization scope ---------------------------------------------- #
    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_UPDATE = "organization.update"
    ORGANIZATION_SETTINGS_MANAGE = "organization.settings.manage"
    ORGANIZATION_MEMBER_READ = "organization.member.read"
    ORGANIZATION_MEMBER_INVITE = "organization.member.invite"
    ORGANIZATION_MEMBER_REMOVE = "organization.member.remove"
    ORGANIZATION_MEMBER_ROLE_CHANGE = "organization.member.role_change"
    ORGANIZATION_INVITATION_READ = "organization.invitation.read"
    ORGANIZATION_INVITATION_REVOKE = "organization.invitation.revoke"
    ORGANIZATION_AUDIT_READ = "organization.audit.read"
    #: Organization-scoped filter and ranking presets: curated configurations
    #: offered to that organization's members and to nobody else.
    ORGANIZATION_QUERY_PRESET_READ = "organization.query_preset.read"
    ORGANIZATION_QUERY_PRESET_MANAGE = "organization.query_preset.manage"

    # --- workspace scope ------------------------------------------------- #
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_PROJECT_CREATE = "workspace.project.create"
    #: Workspace-scoped data capability, for a dataset that belongs to a
    #: workspace without belonging to a project. Evaluated against that one
    #: workspace, so membership of another workspace never satisfies it.
    WORKSPACE_DATASET_CREATE = "workspace.dataset.create"
    WORKSPACE_DATA_READ = "workspace.data.read"
    WORKSPACE_DATA_WRITE = "workspace.data.write"
    WORKSPACE_DATA_IMPORT = "workspace.data.import"
    #: Downloading bytes is its own capability: reading a dataset's metadata
    #: never implies the right to retrieve the genomic content behind it.
    WORKSPACE_DATA_DOWNLOAD = "workspace.data.download"
    WORKSPACE_DATA_DELETE = "workspace.data.delete"
    #: Workspace-scoped analysis capabilities, for an analysis that belongs to a
    #: workspace without belonging to a project.
    WORKSPACE_ANALYSIS_READ = "workspace.analysis.read"
    WORKSPACE_ANALYSIS_CREATE = "workspace.analysis.create"
    WORKSPACE_ANALYSIS_UPDATE = "workspace.analysis.update"
    WORKSPACE_ANALYSIS_EXECUTE = "workspace.analysis.execute"
    WORKSPACE_ANALYSIS_CANCEL = "workspace.analysis.cancel"
    WORKSPACE_ANALYSIS_DELETE = "workspace.analysis.delete"
    WORKSPACE_SCHEDULE_MANAGE = "workspace.schedule.manage"
    WORKSPACE_JOB_READ = "workspace.job.read"
    #: Reading variant records, observations, annotations and evidence held in
    #: the scientific data layer. Separate from dataset read: a dataset's
    #: metadata says nothing about the genomic content derived from it.
    WORKSPACE_VARIANT_READ = "workspace.variant.read"
    #: Reading result sets and their filtered slices.
    WORKSPACE_RESULT_READ = "workspace.result.read"
    #: Accepting a scientific payload into the durable data layer. Held by the
    #: platform's own execution path; a tenant role grants it only where the
    #: tenant may run analyses at all.
    WORKSPACE_RESULT_INGEST = "workspace.result.ingest"
    #: Retrieving result artifact bytes, separate from reading result metadata.
    WORKSPACE_RESULT_DOWNLOAD = "workspace.result.download"
    #: Filtering and ranking are separate capabilities throughout, including in
    #: the permission vocabulary: reading a saved filter is not managing one, and
    #: neither implies anything about ranking.
    WORKSPACE_FILTER_READ = "workspace.filter.read"
    WORKSPACE_FILTER_MANAGE = "workspace.filter.manage"
    WORKSPACE_RANKING_READ = "workspace.ranking.read"
    WORKSPACE_RANKING_MANAGE = "workspace.ranking.manage"
    #: Running a filtered/ranked variant query. Distinct from reading a filter
    #: definition, because executing one reads genomic content.
    WORKSPACE_QUERY_EXECUTE = "workspace.query.execute"
    #: Saved table views: presentation state only, never scientific content.
    WORKSPACE_SAVED_VIEW_MANAGE = "workspace.saved_view.manage"
    #: Reading annotation runs and annotation result metadata for the workspace's
    #: own data. Separate from requesting one, and separate from variant read.
    WORKSPACE_ANNOTATION_READ = "workspace.annotation.read"
    #: Requesting an annotation run against the workspace's own surface. It never
    #: implies any control over the annotation resources themselves.
    WORKSPACE_ANNOTATION_EXECUTE = "workspace.annotation.execute"
    #: Reading evidence records and their provenance for the workspace's own
    #: variants. Separate from variant read and from annotation read: evidence is
    #: its own layer.
    WORKSPACE_EVIDENCE_READ = "workspace.evidence.read"
    #: Recording, importing or withdrawing evidence for the workspace's own
    #: variants. It never implies authority over evidence sources themselves, and
    #: never implies any classification authority.
    WORKSPACE_EVIDENCE_CURATE = "workspace.evidence.curate"
    #: Reading automated criterion evaluations and suggested classifications for
    #: the workspace's own variants. Reading a suggestion is not deciding.
    WORKSPACE_CLASSIFICATION_READ = "workspace.classification.read"
    #: Requesting an automated evaluation from the scientific interpretation
    #: component. It grants no authority over rulesets and no clinical decision.
    WORKSPACE_CLASSIFICATION_EXECUTE = "workspace.classification.execute"
    #: Reading interpretations, their versions, review history and adjudication
    #: record for the workspace's own variants. Reading a decision is not making
    #: one, and it is separate from reading the automated suggestion behind it.
    WORKSPACE_INTERPRETATION_READ = "workspace.interpretation.read"
    #: Opening an interpretation and authoring a version in it. It carries no
    #: authority to adjudicate a disagreement and none to finalize.
    WORKSPACE_INTERPRETATION_AUTHOR = "workspace.interpretation.author"

    # --- project scope --------------------------------------------------- #
    PROJECT_READ = "project.read"
    PROJECT_UPDATE = "project.update"
    PROJECT_ARCHIVE = "project.archive"
    PROJECT_REOPEN = "project.reopen"
    PROJECT_MEMBER_READ = "project.member.read"
    PROJECT_MEMBER_MANAGE = "project.member.manage"
    PROJECT_MEMBER_ROLE_CHANGE = "project.member.role_change"
    PROJECT_OWNERSHIP_TRANSFER = "project.ownership.transfer"
    #: Capability foundations later packages build on. Declared here so that no
    #: later module invents a parallel permission vocabulary, and so that
    #: scientific review stays a distinct responsibility from administration.
    PROJECT_DATA_READ = "project.data.read"
    PROJECT_DATA_WRITE = "project.data.write"
    PROJECT_DATASET_CREATE = "project.dataset.create"
    PROJECT_DATA_IMPORT = "project.data.import"
    #: Retrieval of the actual bytes, separate from metadata read.
    PROJECT_DATA_DOWNLOAD = "project.data.download"
    PROJECT_DATA_DELETE = "project.data.delete"
    PROJECT_ANALYSIS_READ = "project.analysis.read"
    PROJECT_ANALYSIS_CREATE = "project.analysis.create"
    PROJECT_ANALYSIS_UPDATE = "project.analysis.update"
    PROJECT_ANALYSIS_EXECUTE = "project.analysis.execute"
    #: Stopping work in flight is its own capability: being able to start an
    #: analysis never implies the right to cancel someone else's run.
    PROJECT_ANALYSIS_CANCEL = "project.analysis.cancel"
    PROJECT_ANALYSIS_DELETE = "project.analysis.delete"
    PROJECT_SCHEDULE_MANAGE = "project.schedule.manage"
    #: Reading the operational job history of one project's work.
    PROJECT_JOB_READ = "project.job.read"
    PROJECT_INTERPRETATION_REVIEW = "project.interpretation.review"
    PROJECT_REPORT_FINALIZE = "project.report.finalize"
    #: Project-scoped equivalents of the scientific data-layer capabilities.
    PROJECT_VARIANT_READ = "project.variant.read"
    PROJECT_RESULT_READ = "project.result.read"
    PROJECT_RESULT_INGEST = "project.result.ingest"
    PROJECT_RESULT_DOWNLOAD = "project.result.download"
    #: Project-scoped filtering, ranking, query execution and saved views.
    PROJECT_FILTER_READ = "project.filter.read"
    PROJECT_FILTER_MANAGE = "project.filter.manage"
    PROJECT_RANKING_READ = "project.ranking.read"
    PROJECT_RANKING_MANAGE = "project.ranking.manage"
    PROJECT_QUERY_EXECUTE = "project.query.execute"
    PROJECT_SAVED_VIEW_MANAGE = "project.saved_view.manage"
    #: Project-scoped annotation read and annotation execution.
    PROJECT_ANNOTATION_READ = "project.annotation.read"
    PROJECT_ANNOTATION_EXECUTE = "project.annotation.execute"
    #: Project-scoped evidence read and evidence curation.
    PROJECT_EVIDENCE_READ = "project.evidence.read"
    PROJECT_EVIDENCE_CURATE = "project.evidence.curate"
    #: Project-scoped automated evaluation read and execution.
    PROJECT_CLASSIFICATION_READ = "project.classification.read"
    PROJECT_CLASSIFICATION_EXECUTE = "project.classification.execute"
    #: Project-scoped interpretation read and authoring.
    PROJECT_INTERPRETATION_READ = "project.interpretation.read"
    PROJECT_INTERPRETATION_AUTHOR = "project.interpretation.author"
    #: Resolving a disagreement between reviewers. Deliberately not implied by
    #: PROJECT_INTERPRETATION_REVIEW: a reviewer who disagreed must not be able to
    #: rule on their own disagreement by virtue of being a reviewer.
    PROJECT_INTERPRETATION_ADJUDICATE = "project.interpretation.adjudicate"
    #: Closing an interpretation version as the final, immutable decision.
    PROJECT_INTERPRETATION_FINALIZE = "project.interpretation.finalize"

    @property
    def scope(self) -> Scope:
        prefix = self.value.split(".", 1)[0]
        return Scope(prefix)


#: Operations that must never be reachable through an organization-scoped role,
#: however privileged that role is inside its own organization.
PLATFORM_ONLY_PERMISSIONS: frozenset[Permission] = frozenset(
    permission for permission in Permission if permission.scope is Scope.PLATFORM
)

#: Scientific responsibility. Kept explicit so administration never silently
#: implies clinical/scientific review authority.
SCIENTIFIC_REVIEW_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.PROJECT_INTERPRETATION_REVIEW,
        Permission.PROJECT_INTERPRETATION_ADJUDICATE,
        Permission.PROJECT_INTERPRETATION_FINALIZE,
        Permission.PROJECT_REPORT_FINALIZE,
    }
)


__all__ = [
    "PLATFORM_ONLY_PERMISSIONS",
    "SCIENTIFIC_REVIEW_PERMISSIONS",
    "Permission",
    "Scope",
]
