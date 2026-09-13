"use client";

/**
 * Validation run presentation.
 *
 * Severity, category and the *explicit value semantics* of each observed value
 * are shown as the backend reported them. An absent value is never rendered as
 * `0`, `false` or an empty cell: missing, empty, NA, unknown and not-applicable
 * each say what they are, because collapsing them changes scientific meaning.
 */

import { useMemo } from "react";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useApiResource } from "@/hooks/use-api-resource";
import type { ApiClient } from "@/lib/api-client";
import type { ValidationRunSummary } from "@/lib/data-types";
import styles from "../datasets.module.css";

const ABSENT_SEMANTICS = new Set([
  "missing",
  "empty",
  "null",
  "na",
  "unknown",
  "not_applicable",
]);

function semanticsText(semantics: string): string {
  switch (semantics) {
    case "missing":
      return "absent from the record";
    case "empty":
      return "present but empty";
    case "na":
      return "marked NA";
    case "unknown":
      return "marked unknown";
    case "not_applicable":
      return "marked not applicable";
    case "null":
      return "marked null";
    case "zero":
      return "the value zero";
    case "false":
      return "the value false";
    default:
      return "a present value";
  }
}

export function ValidationSummaryBadges({ run }: { run: ValidationRunSummary }) {
  return (
    <span className={styles.badges}>
      <span className={styles.badge}>{run.state.replace(/_/g, " ")}</span>
      {run.blocking_issue_count > 0 ? (
        <span className={`${styles.badge} ${styles.badgeBlocking}`}>
          {run.blocking_issue_count} blocking
        </span>
      ) : null}
      {run.error_issue_count > 0 ? (
        <span className={styles.badge}>{run.error_issue_count} errors</span>
      ) : null}
      {run.warning_issue_count > 0 ? (
        <span className={styles.badge}>{run.warning_issue_count} warnings</span>
      ) : null}
      {run.info_issue_count > 0 ? (
        <span className={styles.badge}>{run.info_issue_count} notes</span>
      ) : null}
      <span className={styles.badge}>
        {run.validator_name} {run.validator_version}
      </span>
    </span>
  );
}

export function ValidationRunDetail({
  client,
  runId,
}: {
  client: ApiClient;
  runId: string;
}) {
  const run = useApiResource(() => client.validationRun(runId), [client, runId]);
  const issues = useMemo(() => run.data?.issues ?? [], [run.data]);

  return (
    <Card title="Validation findings" headingLevel={3}>
      {run.status === "loading" ? (
        <LoadingState label="Loading validation findings" />
      ) : run.status === "error" ? (
        <ErrorState
          description={run.error ?? undefined}
          correlationId={run.correlationId ?? undefined}
        />
      ) : issues.length === 0 ? (
        <EmptyState
          title="No findings recorded"
          description="This run reported nothing. That is not the same as an accepted input: acceptance remains a separate decision."
        />
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">
              Validation findings, {run.data?.issue_total ?? issues.length} in total
            </caption>
            <thead>
              <tr>
                <th scope="col">Severity</th>
                <th scope="col">Category</th>
                <th scope="col">Finding</th>
                <th scope="col">Observed</th>
                <th scope="col">Where</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr key={issue.id}>
                  <td>{issue.severity}</td>
                  <td>{issue.category.replace(/_/g, " ")}</td>
                  <td className={styles.wrap}>
                    <strong>{issue.code.replace(/_/g, " ")}</strong>
                    <br />
                    {issue.message}
                  </td>
                  <td
                    className={
                      ABSENT_SEMANTICS.has(issue.value_semantics)
                        ? styles.semanticsAbsent
                        : undefined
                    }
                  >
                    {issue.observed_value !== null ? <code>{issue.observed_value}</code> : null}
                    {issue.observed_value !== null ? " — " : null}
                    {semanticsText(issue.value_semantics)}
                  </td>
                  <td>
                    {Object.entries(issue.locator)
                      .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`)
                      .join(", ") || "the file as a whole"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
