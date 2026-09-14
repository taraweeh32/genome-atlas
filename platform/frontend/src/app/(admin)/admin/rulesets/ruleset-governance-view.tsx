"use client";

/**
 * Interpretation ruleset governance.
 *
 * A platform administrator reads the registry of ruleset versions, moves a version
 * through its lifecycle, and inspects the controlled benchmark runs recorded against
 * it. Nothing scientific happens here: the criteria and combination rules shown are
 * the declared content of a registered ruleset, and no classification is computed in
 * the browser.
 *
 * A ruleset version is never edited in place. A corrected or respecified guideline is
 * registered as a new version, so classifications naming an earlier version stay
 * reproducible.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { RulesetResponse } from "@/lib/interpretation-types";
import queryStyles from "@/components/query/query.module.css";
import styles from "../administration.module.css";

const LIFECYCLE_STATES = ["active", "deprecated", "retired", "invalidated"] as const;

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "not recorded";
}

export function RulesetGovernanceView() {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const rulesets = useApiResource(() => client.interpretationRulesets({ size: 25 }), [client]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const items = rulesets.data?.items ?? [];
  const selected = items.find((item) => item.id === selectedId) ?? null;

  const runs = useApiResource(
    () =>
      selectedId
        ? client.adminBenchmarkRuns(selectedId, { size: 5 })
        : Promise.resolve({ items: [], page: { number: 1, size: 5, total: 0 } }),
    [client, selectedId],
  );

  const transition = async (ruleset: RulesetResponse, state: string) => {
    setBusy(`${ruleset.id}:${state}`);
    try {
      await client.adminTransitionRuleset(ruleset.id, { state });
      publish({
        tone: "success",
        title: "Ruleset state changed",
        description: `${ruleset.ruleset_key} ${ruleset.version} is now ${label(state)}.`,
      });
      rulesets.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The change was refused",
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={queryStyles.builder}>
      <Card
        title="Ruleset versions"
        description="Each row is one registered version of one interpretation ruleset. A version is never edited in place; a respecification is registered as a new version so historical classifications stay reproducible."
        actions={<Button onClick={rulesets.reload}>Refresh</Button>}
      >
        {rulesets.status === "loading" ? (
          <LoadingState label="Loading rulesets" />
        ) : rulesets.status === "error" ? (
          <ErrorState
            title="The registry could not be read"
            description={rulesets.error ?? ""}
            correlationId={rulesets.correlationId ?? undefined}
            action={
              <Button type="button" variant="secondary" onClick={rulesets.reload}>
                Retry
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No ruleset is registered"
            description="Register and activate a ruleset version before an automated evaluation can reference it."
          />
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Registered ruleset versions</caption>
              <thead>
                <tr>
                  <th scope="col">Ruleset</th>
                  <th scope="col">Version</th>
                  <th scope="col">Guideline</th>
                  <th scope="col">Scope</th>
                  <th scope="col">Combination</th>
                  <th scope="col">Criteria</th>
                  <th scope="col">State</th>
                  <th scope="col">Lifecycle</th>
                </tr>
              </thead>
              <tbody>
                {items.map((ruleset) => (
                  <tr key={ruleset.id}>
                    <td>
                      <button
                        type="button"
                        className={styles.linkButton}
                        onClick={() => setSelectedId(ruleset.id)}
                      >
                        {ruleset.display_name}
                      </button>
                      <div className={styles.muted}>{ruleset.ruleset_key}</div>
                    </td>
                    <td>{ruleset.version}</td>
                    <td>
                      {label(ruleset.guideline_source)}
                      {ruleset.publication_reference ? (
                        <div className={styles.muted}>{ruleset.publication_reference}</div>
                      ) : null}
                    </td>
                    <td>
                      {label(ruleset.specification_scope)}
                      {ruleset.gene_symbol ? (
                        <div className={styles.muted}>{ruleset.gene_symbol}</div>
                      ) : null}
                    </td>
                    <td>{label(ruleset.combination_strategy)}</td>
                    <td>{ruleset.criteria.length}</td>
                    <td>
                      <span className={styles.badge}>{label(ruleset.state)}</span>
                      {ruleset.is_usable ? null : (
                        <div className={styles.muted}>cannot be evaluated against</div>
                      )}
                    </td>
                    <td>
                      <div className={styles.actions}>
                        {LIFECYCLE_STATES.filter((state) => state !== ruleset.state).map(
                          (state) => (
                            <Button
                              key={state}
                              type="button"
                              variant="secondary"
                              disabled={busy !== null}
                              onClick={() => transition(ruleset, state)}
                            >
                              {busy === `${ruleset.id}:${state}` ? "Working" : label(state)}
                            </Button>
                          ),
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selected ? (
        <Card
          title={`${selected.display_name} ${selected.version}`}
          description="The declared content of this ruleset version: its criteria, the strengths each criterion permits, and the rules by which the engine combines applied criteria into a classification."
        >
          <DefinitionList
            items={[
              { term: "Guideline source", value: label(selected.guideline_source) },
              { term: "Citation", value: selected.guideline_citation ?? "not declared" },
              {
                term: "Publication",
                value: selected.publication_reference
                  ? `${selected.publication_reference}${selected.publication_year ? ` (${selected.publication_year})` : ""}`
                  : "not declared",
              },
              { term: "Capability", value: selected.capability_id ?? "not declared" },
              { term: "Assembly", value: selected.genome_assembly ?? "not declared" },
              {
                term: "Configuration digest",
                value: selected.configuration_digest ?? "not recorded",
              },
              { term: "Effective from", value: moment(selected.effective_from) },
              { term: "Activated", value: moment(selected.activated_at) },
            ]}
          />
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Declared criteria</caption>
              <thead>
                <tr>
                  <th scope="col">Criterion</th>
                  <th scope="col">Family</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Default strength</th>
                  <th scope="col">Permitted strengths</th>
                  <th scope="col">Evidence required</th>
                </tr>
              </thead>
              <tbody>
                {selected.criteria.map((criterion) => (
                  <tr key={criterion.criterion_key}>
                    <td>
                      {criterion.criterion_key}
                      {criterion.description ? (
                        <div className={styles.muted}>{criterion.description}</div>
                      ) : null}
                    </td>
                    <td>{label(criterion.family)}</td>
                    <td>{label(criterion.direction)}</td>
                    <td>{label(criterion.default_strength)}</td>
                    <td>{criterion.permitted_strengths.map(label).join(", ")}</td>
                    <td>{criterion.requires_evidence ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Declared combination rules</caption>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">Yields</th>
                  <th scope="col">Precedence</th>
                  <th scope="col">Description</th>
                </tr>
              </thead>
              <tbody>
                {selected.combination_rules.map((rule) => (
                  <tr key={rule.rule_key}>
                    <td>{rule.rule_key}</td>
                    <td>{label(rule.classification)}</td>
                    <td>{rule.precedence ?? "—"}</td>
                    <td>{rule.description ?? "not declared"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {selected ? (
        <Card
          title="Benchmark runs"
          description="Controlled cases recorded against this ruleset version. A contract run checks that the engine behaves deterministically and reproducibly; only a run whose cases carry externally established expected classifications is an accuracy run. No clinical accuracy is claimed from a contract run."
          actions={<Button onClick={runs.reload}>Refresh</Button>}
        >
          {runs.status === "loading" ? (
            <LoadingState label="Loading benchmark runs" />
          ) : runs.status === "error" ? (
            <ErrorState
              title="The benchmark runs could not be read"
              description={runs.error ?? ""}
              correlationId={runs.correlationId ?? undefined}
            />
          ) : (runs.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No benchmark run is recorded"
              description="Register benchmark cases and record a run to validate deterministic engine behaviour."
            />
          ) : (
            runs.data?.items.map((run) => (
              <DefinitionList
                key={run.id}
                items={[
                  { term: "Validation kind", value: label(run.validation_kind) },
                  {
                    term: "Claim",
                    value: run.is_accuracy_run
                      ? "scientific accuracy against expected classifications"
                      : "structural and contract validation only",
                  },
                  { term: "Cases", value: run.case_count },
                  { term: "Matched", value: run.matched_count },
                  { term: "Mismatched", value: run.mismatched_count },
                  { term: "Not evaluated", value: run.not_evaluated_count },
                  { term: "Executed", value: moment(run.executed_at) },
                ]}
              />
            ))
          )}
        </Card>
      ) : null}
    </div>
  );
}
