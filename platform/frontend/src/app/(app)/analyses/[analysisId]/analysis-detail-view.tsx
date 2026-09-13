"use client";

/**
 * One analysis: its configuration versions, its executions and the recorded
 * provenance of a selected execution.
 *
 * Rules this surface obeys:
 * - Requesting an execution asks the server to queue durable work. The response
 *   is a queued execution, not a result, and the UI says so.
 * - Cancellation is a *request*. `can_cancel` comes from the server, and a
 *   requested cancellation is displayed as requested until the server reports
 *   the execution actually stopped.
 * - Provenance is read-only recorded fact. A missing engine version, container
 *   digest or node identity is shown as unrecorded, never filled in.
 * - Artifacts are referenced. They are never inlined or interpreted here.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import styles from "../analyses.module.css";
import { label } from "../analyses-view";

const TERMINAL_EXECUTION_STATES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "expired",
  "rejected",
]);

function moment(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function recorded(value: string | null | undefined): string {
  return value && value.length > 0 ? value : "not recorded";
}

export function AnalysisDetailView({ analysisId }: { analysisId: string }) {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
  const [isBusy, setBusy] = useState(false);

  const analysis = useApiResource(() => client.analysis(analysisId), [client, analysisId]);
  const configurations = useApiResource(
    () => client.analysisConfigurations(analysisId),
    [client, analysisId],
  );
  const executions = useApiResource(
    () => client.executions({ analysis_id: analysisId }),
    [client, analysisId],
  );
  const provenance = useApiResource(
    () =>
      selectedExecutionId
        ? client.executionProvenance(selectedExecutionId)
        : Promise.resolve(null),
    [client, selectedExecutionId],
  );

  function report(title: string, cause: unknown) {
    const error = cause instanceof ApiError ? cause : null;
    publish({
      tone: "danger",
      title,
      description: error?.message ?? "The platform API could not be reached.",
      correlationId: error?.correlationId,
    });
  }

  async function requestExecution() {
    setBusy(true);
    try {
      await client.requestExecution(analysisId, {});
      publish({
        tone: "success",
        title: "Execution queued",
        description: "The platform queued durable work. Progress is reported by the server.",
      });
      executions.reload();
      analysis.reload();
    } catch (cause) {
      report("The execution was not queued", cause);
    } finally {
      setBusy(false);
    }
  }

  async function activate(configurationId: string) {
    setBusy(true);
    try {
      await client.activateAnalysisConfiguration(analysisId, configurationId);
      publish({ tone: "success", title: "Configuration version activated" });
      configurations.reload();
      analysis.reload();
    } catch (cause) {
      report("The configuration was not activated", cause);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(executionId: string) {
    setBusy(true);
    try {
      await client.cancelExecution(executionId, {});
      publish({
        tone: "info",
        title: "Cancellation requested",
        description: "A request to stop is not proof that work stopped. The server reports the outcome.",
      });
      executions.reload();
    } catch (cause) {
      report("The cancellation was not accepted", cause);
    } finally {
      setBusy(false);
    }
  }

  if (analysis.status === "loading") {
    return (
      <Card title="Analysis">
        <LoadingState label="Loading analysis" />
      </Card>
    );
  }

  if (analysis.status === "error" || !analysis.data) {
    return (
      <Card title="Analysis">
        <ErrorState
          title={analysis.isForbidden ? "Not available to you" : "Something went wrong"}
          description={
            analysis.isForbidden
              ? "This analysis does not exist or you may not read it. The platform does not distinguish between the two."
              : (analysis.error ?? undefined)
          }
          correlationId={analysis.correlationId ?? undefined}
          action={analysis.isForbidden ? undefined : <Button onClick={analysis.reload}>Try again</Button>}
        />
      </Card>
    );
  }

  const definition = analysis.data;
  const capabilities = new Set(definition.capabilities);

  return (
    <>
      <Card
        title={definition.name}
        description={definition.description ?? "No description was recorded."}
        actions={
          capabilities.has("execute") && definition.is_executable ? (
            <Button variant="primary" onClick={requestExecution} isBusy={isBusy}>
              Queue execution
            </Button>
          ) : undefined
        }
      >
        <dl className={styles.provenance}>
          <dt>Kind</dt>
          <dd>{label(definition.kind)}</dd>
          <dt>State</dt>
          <dd>{label(definition.state)}</dd>
          <dt>Requested capability</dt>
          <dd>{recorded(definition.capability_key)}</dd>
          <dt>Current configuration version</dt>
          <dd>{recorded(definition.current_configuration_id)}</dd>
          <dt>Project</dt>
          <dd>
            <Link href={`/projects/${definition.project_id}`}>{definition.project_id}</Link>
          </dd>
        </dl>
        {definition.is_executable ? null : (
          <p className={styles.muted}>
            The server reports this analysis as not runnable yet. It needs an active configuration
            version whose declared inputs are accepted dataset versions.
          </p>
        )}
      </Card>

      <Card
        title="Configuration versions"
        description="Each version is immutable. Activating one changes which version a new execution uses and never alters an execution already recorded."
        actions={<Button onClick={configurations.reload}>Refresh</Button>}
      >
        {configurations.status === "loading" ? (
          <LoadingState label="Loading configuration versions" />
        ) : configurations.status === "error" ? (
          <ErrorState
            description={configurations.error ?? undefined}
            correlationId={configurations.correlationId ?? undefined}
          />
        ) : configurations.data && configurations.data.items.length > 0 ? (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Configuration versions of this analysis</caption>
              <thead>
                <tr>
                  <th scope="col" className={styles.numeric}>
                    Version
                  </th>
                  <th scope="col">Label</th>
                  <th scope="col">Validation</th>
                  <th scope="col" className={styles.numeric}>
                    Inputs
                  </th>
                  <th scope="col">Created</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {configurations.data.items.map((configuration) => (
                  <tr key={configuration.id}>
                    <td className={styles.numeric}>{configuration.version_number}</td>
                    <td className={styles.wide}>{configuration.label ?? "—"}</td>
                    <td>
                      <span className={styles.badge}>{label(configuration.validation_state)}</span>
                    </td>
                    <td className={styles.numeric}>{configuration.inputs.length}</td>
                    <td>{moment(configuration.created_at)}</td>
                    <td>
                      {configuration.is_current ? (
                        <span className={styles.badge}>current</span>
                      ) : capabilities.has("update") ? (
                        <Button onClick={() => activate(configuration.id)} isBusy={isBusy}>
                          Activate
                        </Button>
                      ) : (
                        <span className={styles.muted}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No configuration version yet"
            description="An analysis cannot run until a configuration version declares its inputs, parameters and scientific resources."
          />
        )}
      </Card>

      <Card
        title="Executions"
        description="One row per requested run. Re-running never overwrites an earlier execution."
        actions={<Button onClick={executions.reload}>Refresh</Button>}
      >
        {executions.status === "loading" ? (
          <LoadingState label="Loading executions" />
        ) : executions.status === "error" ? (
          <ErrorState
            description={executions.error ?? undefined}
            correlationId={executions.correlationId ?? undefined}
          />
        ) : executions.data && executions.data.items.length > 0 ? (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Executions of this analysis</caption>
              <thead>
                <tr>
                  <th scope="col" className={styles.numeric}>
                    Attempt
                  </th>
                  <th scope="col">State</th>
                  <th scope="col">Progress</th>
                  <th scope="col">Queue</th>
                  <th scope="col">Requested</th>
                  <th scope="col">Completed</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {executions.data.items.map((execution) => (
                  <tr key={execution.id}>
                    <td className={styles.numeric}>{execution.attempt_sequence}</td>
                    <td>
                      <span className={styles.badge}>{label(execution.state)}</span>
                      {execution.failure_code ? (
                        <p className={styles.muted}>
                          {execution.failure_code}: {execution.failure_message ?? "no detail recorded"}
                        </p>
                      ) : null}
                    </td>
                    <td>
                      {execution.progress_percent === null
                        ? TERMINAL_EXECUTION_STATES.has(execution.state)
                          ? "—"
                          : "not reported"
                        : `${execution.progress_percent}%`}
                    </td>
                    <td>
                      {execution.queue} · priority {execution.priority}
                    </td>
                    <td>{moment(execution.requested_at)}</td>
                    <td>{moment(execution.completed_at)}</td>
                    <td>
                      <div className={styles.actions}>
                        <Button onClick={() => setSelectedExecutionId(execution.id)}>
                          Provenance
                        </Button>
                        {execution.can_cancel ? (
                          <Button variant="danger" onClick={() => cancel(execution.id)} isBusy={isBusy}>
                            Request cancel
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No execution recorded"
            description="Nothing has been run for this analysis yet."
          />
        )}
      </Card>

      {selectedExecutionId ? (
        <Card
          title="Execution provenance"
          description="Recorded facts about one run: the configuration it was frozen with, the scientific engine and environment that answered, and the artifacts produced."
          actions={<Button onClick={() => setSelectedExecutionId(null)}>Close</Button>}
        >
          {provenance.status === "loading" ? (
            <LoadingState label="Loading provenance" />
          ) : provenance.status === "error" ? (
            <ErrorState
              description={provenance.error ?? undefined}
              correlationId={provenance.correlationId ?? undefined}
            />
          ) : provenance.data ? (
            <>
              <dl className={styles.provenance}>
                <dt>Execution</dt>
                <dd>{provenance.data.execution.id}</dd>
                <dt>Correlation ID</dt>
                <dd>{provenance.data.execution.correlation_id}</dd>
                <dt>Compute node</dt>
                <dd>{recorded(provenance.data.execution.compute_node_id)}</dd>
                <dt>Configuration version</dt>
                <dd>{provenance.data.execution.analysis_configuration_id}</dd>
              </dl>
              {provenance.data.scientific_executions.length === 0 ? (
                <EmptyState
                  title="No scientific execution recorded"
                  description="This execution has not been submitted to the scientific subsystem yet."
                />
              ) : (
                provenance.data.scientific_executions.map((run) => (
                  <dl key={run.id} className={styles.provenance}>
                    <dt>Capability</dt>
                    <dd>
                      {run.capability_key} {run.capability_version ? `(${run.capability_version})` : ""}
                    </dd>
                    <dt>State</dt>
                    <dd>{label(run.state)}</dd>
                    <dt>Engine version</dt>
                    <dd>{recorded(run.engine_version)}</dd>
                    <dt>Environment version</dt>
                    <dd>{recorded(run.environment_version)}</dd>
                    <dt>Container image digest</dt>
                    <dd>{recorded(run.container_image_digest)}</dd>
                    <dt>Node identity</dt>
                    <dd>{recorded(run.node_identity)}</dd>
                    <dt>Artifacts</dt>
                    <dd>
                      {run.artifacts.length === 0
                        ? "none recorded"
                        : run.artifacts
                            .map((artifact) => `${artifact.artifact_key} (${artifact.artifact_kind})`)
                            .join(", ")}
                    </dd>
                  </dl>
                ))
              )}
            </>
          ) : null}
        </Card>
      ) : null}
    </>
  );
}
