"use client";

/**
 * The interpretation and review workspace.
 *
 * What this surface is careful about:
 *
 * - **Four decision kinds stay four things.** The automated suggestion, each
 *   reviewer decision, the adjudicated decision and the final interpretation are
 *   displayed separately, labelled by their decision role. Nothing is merged into
 *   a single "classification" line.
 * - **Disagreement is not tidied away.** Every recorded decision is listed,
 *   including ones that were overruled, with its author and timestamp.
 * - **Stale work cannot land quietly.** A reviewer decision carries the version
 *   number the reviewer was looking at; the backend rejects it when newer work
 *   arrived, and the refusal is shown rather than retried.
 * - **No scientific computation happens here.** Classification values are
 *   recorded choices, and criterion and evidence identifiers are pinned by
 *   reference. The browser never derives, scores or ranks anything.
 */

import { useMemo, useState } from "react";
import { authStyles as formStyles } from "@/components/auth/field";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useWorkspace } from "@/context/workspace-context";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import {
  CLASSIFICATIONS,
  REVIEW_DECISIONS,
  type InterpretationDetailResponse,
  type InterpretationVersionResponse,
} from "@/lib/review-types";
import styles from "../results/results.module.css";

const EMPTY_PAGE = { items: [], page: { number: 1, size: 0, total: 0 } } as const;

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "not recorded";
}

/** Reviewer positions grouped by what they proposed, as the backend recorded it. */
function disagreementLines(summary: Record<string, unknown>): readonly string[] {
  const positions = summary["positions"];
  if (!positions || typeof positions !== "object") return [];
  return Object.entries(positions as Record<string, unknown>).map(
    ([classification, reviewers]) =>
      `${label(classification)}: ${
        Array.isArray(reviewers) ? reviewers.length : 1
      } reviewer(s)`,
  );
}

function VersionRow({ version }: { version: InterpretationVersionResponse }) {
  return (
    <tr>
      <td className={styles.numeric}>{version.version_number}</td>
      <td>
        <span className={styles.badge}>{label(version.decision_role)}</span>
      </td>
      <td>{label(version.classification)}</td>
      <td>
        {version.suggested_classification ? (
          label(version.suggested_classification)
        ) : (
          <span className={styles.muted}>no automated suggestion</span>
        )}
      </td>
      <td className={styles.numeric}>{version.review_round}</td>
      <td>
        {version.ruleset_version ? (
          <code>{version.ruleset_version}</code>
        ) : (
          <span className={styles.muted}>not pinned</span>
        )}
      </td>
      <td className={styles.numeric}>{version.criterion_evaluation_ids.length}</td>
      <td className={styles.numeric}>{version.evidence_item_ids.length}</td>
      <td>
        {version.finalized_at ? (
          <span className={styles.badge}>finalized {moment(version.finalized_at)}</span>
        ) : (
          <span className={styles.muted}>open</span>
        )}
      </td>
    </tr>
  );
}

export function InterpretationReviewView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const workspaceId = activeWorkspace?.id ?? null;

  const [assignedToMe, setAssignedToMe] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [decision, setDecision] = useState<string>("accept");
  const [proposed, setProposed] = useState<string>("");
  const [criterionId, setCriterionId] = useState("");
  const [rationale, setRationale] = useState("");
  const [finalClassification, setFinalClassification] = useState<string>("uncertain_significance");
  const [reviewerId, setReviewerId] = useState("");
  const [reviewRole, setReviewRole] = useState("reviewer");

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionCorrelation, setActionCorrelation] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);

  const interpretations = useApiResource(
    () =>
      workspaceId
        ? client.interpretations({
            workspace_id: workspaceId,
            assigned_to_me: assignedToMe || undefined,
          })
        : Promise.resolve(EMPTY_PAGE),
    [client, workspaceId, assignedToMe],
  );

  const detail = useApiResource<InterpretationDetailResponse | null>(
    () => (selectedId ? client.interpretation(selectedId) : Promise.resolve(null)),
    [client, selectedId],
  );

  async function run(note: string, action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    setActionCorrelation(null);
    setActionNote(null);
    try {
      await action();
      setActionNote(note);
      detail.reload();
      interpretations.reload();
    } catch (cause) {
      const apiError = cause instanceof ApiError ? cause : null;
      setActionError(apiError?.message ?? "The platform API could not be reached.");
      setActionCorrelation(apiError?.correlationId ?? null);
    } finally {
      setBusy(false);
    }
  }

  if (resolution !== "resolved" || !activeWorkspace) {
    return (
      <Card title="Workspace context">
        {resolution === "error" ? (
          <ErrorState description="Workspaces could not be loaded, so no interpretations can be listed." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  const items = interpretations.data?.items ?? [];
  const record = detail.data;
  const current = record?.current_version ?? null;
  const isFinalized = Boolean(current?.finalized_at);
  const expected = record?.interpretation.current_version_number ?? 0;

  return (
    <>
      <Card
        title="Decision records"
        description="Interpretations in this workspace. Visibility is decided by the backend for each record."
        actions={
          <Button
            variant={assignedToMe ? "primary" : "secondary"}
            size="sm"
            onClick={() => setAssignedToMe((value) => !value)}
          >
            {assignedToMe ? "Showing my review queue" : "Show my review queue"}
          </Button>
        }
      >
        {interpretations.status === "loading" ? (
          <LoadingState label="Loading interpretations" />
        ) : interpretations.status === "error" ? (
          <ErrorState
            description={interpretations.error ?? undefined}
            correlationId={interpretations.correlationId ?? undefined}
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No interpretations"
            description="Nothing has been opened for review in this workspace yet."
          />
        ) : (
          <div className={styles.scroll}>
            <table className={`${styles.table} ${styles.dense}`}>
              <thead>
                <tr>
                  <th scope="col">Variant</th>
                  <th scope="col">Condition</th>
                  <th scope="col">State</th>
                  <th scope="col">Review</th>
                  <th scope="col">Version</th>
                  <th scope="col">Opened</th>
                  <th scope="col">Open</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <code>{item.variant_id}</code>
                    </td>
                    <td>
                      {item.condition_term ??
                        item.condition_identifier ?? (
                          <span className={styles.muted}>no condition context</span>
                        )}
                    </td>
                    <td>
                      <span className={styles.badge}>{label(item.state)}</span>
                    </td>
                    <td>{label(item.review_state)}</td>
                    <td className={styles.numeric}>{item.current_version_number}</td>
                    <td>{moment(item.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className={styles.linkButton}
                        onClick={() => setSelectedId(item.id)}
                      >
                        Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selectedId === null ? null : detail.status === "loading" ? (
        <Card title="Decision record">
          <LoadingState label="Loading the decision record" />
        </Card>
      ) : detail.status === "error" || !record ? (
        <Card title="Decision record">
          <ErrorState
            description={detail.error ?? "This interpretation is not available to you."}
            correlationId={detail.correlationId ?? undefined}
          />
        </Card>
      ) : (
        <>
          <Card
            title="Context and current position"
            description="The variant, the condition context, and the decision currently standing."
          >
            <DefinitionList
              items={[
                { term: "Variant", value: <code>{record.interpretation.variant_id}</code> },
                { term: "Project", value: <code>{record.interpretation.project_id}</code> },
                {
                  term: "Condition",
                  value:
                    record.interpretation.condition_term ??
                    record.interpretation.condition_identifier ??
                    "no condition context",
                },
                { term: "State", value: label(record.interpretation.state) },
                { term: "Review state", value: label(record.interpretation.review_state) },
                {
                  term: "Automated suggestion",
                  value: current?.suggested_classification
                    ? label(current.suggested_classification)
                    : "none recorded",
                },
                {
                  term: "Decision standing",
                  value: current
                    ? `${label(current.classification)} (${label(current.decision_role)})`
                    : "no version recorded",
                },
                {
                  term: "Ruleset pinned",
                  value: current?.ruleset_version ?? "not pinned",
                },
                {
                  term: "Rationale",
                  value: current?.rationale ?? "none recorded",
                },
                {
                  term: "Finalized",
                  value: current?.finalized_at
                    ? `${moment(current.finalized_at)} — closed; a correction opens a successor`
                    : "not finalized",
                },
              ]}
            />
            {current && disagreementLines(current.disagreement_summary).length > 0 ? (
              <>
                <p className={styles.muted}>Disagreement recorded on this version:</p>
                <ul>
                  {disagreementLines(current.disagreement_summary).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </Card>

          <Card
            title="Version history"
            description="Every version, with the role of the decision it records. Nothing here is rewritten."
          >
            <div className={styles.scroll}>
              <table className={`${styles.table} ${styles.dense}`}>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Decision role</th>
                    <th scope="col">Recorded</th>
                    <th scope="col">Automated suggestion</th>
                    <th scope="col">Round</th>
                    <th scope="col">Ruleset</th>
                    <th scope="col">Criteria</th>
                    <th scope="col">Evidence</th>
                    <th scope="col">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {record.versions.map((version) => (
                    <VersionRow key={version.id} version={version} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card
            title="Reviewers"
            description="Assignments for the current and earlier review rounds."
          >
            {record.assignments.length === 0 ? (
              <EmptyState title="No reviewers assigned" />
            ) : (
              <table className={`${styles.table} ${styles.dense}`}>
                <thead>
                  <tr>
                    <th scope="col">Reviewer</th>
                    <th scope="col">Role</th>
                    <th scope="col">State</th>
                    <th scope="col">Round</th>
                    <th scope="col">Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {record.assignments.map((assignment) => (
                    <tr key={assignment.id}>
                      <td>
                        <code>{assignment.reviewer_user_id}</code>
                      </td>
                      <td>{label(assignment.review_role)}</td>
                      <td>{label(assignment.state)}</td>
                      <td className={styles.numeric}>{assignment.review_round}</td>
                      <td>{moment(assignment.completed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card
            title="Decision history"
            description="Append-only. Overruled and rejected positions stay on the record."
          >
            {record.decisions.length === 0 ? (
              <EmptyState title="No decisions recorded" />
            ) : (
              <div className={styles.scroll}>
                <table className={`${styles.table} ${styles.dense}`}>
                  <thead>
                    <tr>
                      <th scope="col">Decided</th>
                      <th scope="col">Reviewer</th>
                      <th scope="col">Decision</th>
                      <th scope="col">Role</th>
                      <th scope="col">Proposed</th>
                      <th scope="col">Criterion</th>
                      <th scope="col">Round</th>
                      <th scope="col">Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {record.decisions.map((item) => (
                      <tr key={item.id}>
                        <td>{moment(item.decided_at)}</td>
                        <td>
                          <code>{item.reviewer_user_id}</code>
                        </td>
                        <td>{label(item.decision)}</td>
                        <td>
                          <span className={styles.badge}>{label(item.decision_role)}</span>
                        </td>
                        <td>
                          {item.proposed_classification ? (
                            label(item.proposed_classification)
                          ) : (
                            <span className={styles.muted}>none</span>
                          )}
                        </td>
                        <td>
                          {item.criterion_evaluation_id ? (
                            <code>{item.criterion_evaluation_id}</code>
                          ) : (
                            <span className={styles.muted}>classification level</span>
                          )}
                        </td>
                        <td className={styles.numeric}>{item.review_round}</td>
                        <td>
                          {item.rationale ?? <span className={styles.muted}>none recorded</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card
            title="Record your action"
            description="Each action is authorized separately by the backend: reviewing, adjudicating and finalizing are three different authorities."
          >
            {actionError ? (
              <ErrorState
                title="The platform refused this action"
                description={actionError}
                correlationId={actionCorrelation ?? undefined}
              />
            ) : null}
            {actionNote ? <p className={styles.muted}>{actionNote}</p> : null}
            {isFinalized ? (
              <p className={styles.muted}>
                This interpretation is finalized and cannot be changed. A correction is
                recorded as a new interpretation.
              </p>
            ) : null}

            <div className={formStyles.form}>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="review-decision">
                  Reviewer decision
                </label>
                <select
                  id="review-decision"
                  className={formStyles.input}
                  value={decision}
                  onChange={(event) => setDecision(event.target.value)}
                >
                  {REVIEW_DECISIONS.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </select>
              </div>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="review-proposed">
                  Classification you propose (optional)
                </label>
                <select
                  id="review-proposed"
                  className={formStyles.input}
                  value={proposed}
                  onChange={(event) => setProposed(event.target.value)}
                >
                  <option value="">no proposal</option>
                  {CLASSIFICATIONS.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </select>
              </div>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="review-criterion">
                  Criterion evaluation identifier (for criterion-level decisions)
                </label>
                <input
                  id="review-criterion"
                  className={formStyles.input}
                  value={criterionId}
                  onChange={(event) => setCriterionId(event.target.value)}
                />
              </div>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="review-rationale">
                  Rationale
                </label>
                <textarea
                  id="review-rationale"
                  className={formStyles.input}
                  rows={3}
                  value={rationale}
                  onChange={(event) => setRationale(event.target.value)}
                />
                <p className={formStyles.hint}>
                  Recorded verbatim and attributed to you. Overrides and finalization
                  require one.
                </p>
              </div>

              <div className={styles.actions}>
                <Button
                  variant="primary"
                  isBusy={busy}
                  disabled={!current || isFinalized}
                  onClick={() =>
                    run("Your decision was recorded.", () =>
                      client.recordReviewDecision(record.interpretation.id, {
                        interpretation_version_id: current?.id,
                        decision,
                        rationale: rationale.trim() === "" ? undefined : rationale,
                        criterion_evaluation_id:
                          criterionId.trim() === "" ? undefined : criterionId.trim(),
                        proposed_classification: proposed === "" ? undefined : proposed,
                        expected_current_version_number: expected,
                      }),
                    )
                  }
                >
                  Record decision
                </Button>
                <Button
                  isBusy={busy}
                  disabled={isFinalized}
                  onClick={() =>
                    run("Your review was submitted.", () =>
                      client.submitReview(record.interpretation.id),
                    )
                  }
                >
                  Submit my review
                </Button>
              </div>
            </div>

            <div className={formStyles.form}>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="final-classification">
                  Adjudicated classification
                </label>
                <select
                  id="final-classification"
                  className={formStyles.input}
                  value={finalClassification}
                  onChange={(event) => setFinalClassification(event.target.value)}
                >
                  {CLASSIFICATIONS.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </select>
                <p className={formStyles.hint}>
                  Adjudication resolves reviewer disagreement. It does not delete the
                  positions it resolved.
                </p>
              </div>
              <div className={styles.actions}>
                <Button
                  isBusy={busy}
                  disabled={isFinalized}
                  onClick={() =>
                    run("The adjudicated decision was recorded.", () =>
                      client.adjudicateInterpretation(record.interpretation.id, {
                        classification: finalClassification,
                        rationale,
                      }),
                    )
                  }
                >
                  Adjudicate
                </Button>
                <Button
                  isBusy={busy}
                  disabled={isFinalized}
                  onClick={() =>
                    run("The interpretation was finalized and is now closed.", () =>
                      client.finalizeInterpretation(record.interpretation.id, {
                        rationale,
                        expected_version_number: expected,
                      }),
                    )
                  }
                >
                  Finalize
                </Button>
                <Button
                  isBusy={busy}
                  disabled={!isFinalized}
                  onClick={() =>
                    run("A successor interpretation was opened.", () =>
                      client.reclassifyInterpretation(record.interpretation.id, {
                        reason: rationale,
                      }),
                    )
                  }
                >
                  Reclassify
                </Button>
              </div>
            </div>

            <div className={formStyles.form}>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="reviewer-id">
                  Assign a reviewer
                </label>
                <input
                  id="reviewer-id"
                  className={formStyles.input}
                  value={reviewerId}
                  onChange={(event) => setReviewerId(event.target.value)}
                  placeholder="user identifier"
                />
              </div>
              <div className={formStyles.field}>
                <label className={formStyles.label} htmlFor="reviewer-role">
                  Role
                </label>
                <select
                  id="reviewer-role"
                  className={formStyles.input}
                  value={reviewRole}
                  onChange={(event) => setReviewRole(event.target.value)}
                >
                  <option value="reviewer">reviewer</option>
                  <option value="adjudicator">adjudicator</option>
                </select>
              </div>
              <div className={styles.actions}>
                <Button
                  isBusy={busy}
                  disabled={reviewerId.trim() === "" || isFinalized}
                  onClick={() =>
                    run("The reviewer was assigned.", () =>
                      client.assignReviewer(record.interpretation.id, {
                        reviewer_user_id: reviewerId.trim(),
                        review_role: reviewRole,
                      }),
                    )
                  }
                >
                  Assign
                </Button>
              </div>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
