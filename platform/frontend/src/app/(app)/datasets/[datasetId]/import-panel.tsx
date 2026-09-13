"use client";

/**
 * Column mapping and import submission for one verified artifact.
 *
 * The mapping is a human decision recorded as such: the platform may suggest a
 * target concept, but a suggestion and a confirmation are stored distinctly and
 * shown distinctly here. Submitting queues a durable import job; the browser
 * never processes the file, and a passing import still does not accept the
 * version.
 */

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { ColumnMappingDecision, ImportSessionResponse } from "@/lib/data-types";
import styles from "../datasets.module.css";
import { ValidationRunDetail, ValidationSummaryBadges } from "./validation-issues";

/** Concepts the backend accepts, mirroring the API contract exactly. */
const CONCEPTS: readonly { value: string; label: string }[] = [
  { value: "chromosome", label: "Chromosome" },
  { value: "position", label: "Position" },
  { value: "reference_allele", label: "Reference allele" },
  { value: "alternate_allele", label: "Alternate allele" },
  { value: "variant_identifier", label: "Variant identifier" },
  { value: "gene_symbol", label: "Gene symbol" },
  { value: "transcript_identifier", label: "Transcript identifier" },
  { value: "consequence", label: "Consequence" },
  { value: "sample_identifier", label: "Sample identifier" },
  { value: "genotype", label: "Genotype" },
  { value: "zygosity", label: "Zygosity" },
  { value: "read_depth", label: "Read depth" },
  { value: "allele_frequency", label: "Allele frequency" },
  { value: "quality", label: "Quality" },
  { value: "filter_status", label: "Filter status" },
  { value: "phenotype_term", label: "Phenotype term" },
  { value: "passthrough", label: "Keep as source metadata" },
  { value: "ignored", label: "Ignore this column" },
];

export function ImportPanel({
  client,
  artifactId,
  onChanged,
}: {
  client: ApiClient;
  artifactId: string;
  onChanged(): void;
}) {
  const { publish } = useToasts();
  const [session, setSession] = useState<ImportSessionResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [choices, setChoices] = useState<Record<number, string>>({});
  const [isBusy, setBusy] = useState(false);

  useEffect(() => {
    setSession(null);
    setStatus("idle");
    setMessage(null);
  }, [artifactId]);

  const suggested = useMemo(
    () => (session ? session.mappings.filter((item) => item.origin === "system_suggested") : []),
    [session],
  );

  function adopt(next: ImportSessionResponse) {
    setSession(next);
    setChoices(
      Object.fromEntries(
        next.mappings.map((item) => [item.source_column_index, item.target_concept]),
      ),
    );
  }

  async function run<T>(action: () => Promise<T>, failure: string): Promise<T | null> {
    setBusy(true);
    try {
      return await action();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: failure,
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function open() {
    setStatus("loading");
    const opened = await run(
      () => client.openImportSession(artifactId),
      "The import could not be opened",
    );
    if (opened) {
      adopt(opened);
      setStatus("idle");
    } else {
      setStatus("error");
      setMessage("The platform refused to open an import for this file.");
    }
  }

  async function confirm() {
    if (!session) return;
    const decisions: ColumnMappingDecision[] = session.mappings.map((item) => ({
      source_column_index: item.source_column_index,
      source_column_name: item.source_column_name,
      target_concept: choices[item.source_column_index] ?? item.target_concept,
    }));
    const confirmed = await run(
      () => client.confirmColumnMapping(session.id, decisions),
      "The mapping was not confirmed",
    );
    if (confirmed) {
      adopt(confirmed);
      publish({
        tone: "success",
        title: "Mapping confirmed",
        description: "Your decisions are recorded as human-confirmed, separately from suggestions.",
      });
    }
  }

  async function submit() {
    if (!session) return;
    const submitted = await run(
      () => client.submitImport(session.id),
      "The import was not submitted",
    );
    if (submitted) {
      adopt(submitted);
      publish({
        tone: "success",
        title: "Import submitted",
        description: "A durable job will execute it. A passing import validates the version; accepting it stays a separate decision.",
      });
      onChanged();
    }
  }

  if (!session) {
    return (
      <Card
        title="Import this file"
        description="An import records what each source column means, as a decision made by a person, before anything is read as a platform concept."
        headingLevel={3}
      >
        {status === "loading" ? (
          <LoadingState label="Opening an import session" />
        ) : status === "error" ? (
          <ErrorState description={message ?? undefined} />
        ) : (
          <Button variant="primary" isBusy={isBusy} onClick={() => void open()}>
            Start an import
          </Button>
        )}
      </Card>
    );
  }

  return (
    <>
      <Card
        title="Column mapping"
        description={`Detected format: ${session.detected_format.replace(/_/g, " ")}. ${
          suggested.length > 0
            ? `${suggested.length} of ${session.mappings.length} mappings are still platform suggestions, not decisions.`
            : "Every mapping below has been confirmed by a person."
        }`}
        headingLevel={3}
        actions={
          <>
            <Button isBusy={isBusy} onClick={() => void confirm()}>
              Confirm mapping
            </Button>
            <Button
              variant="primary"
              disabled={session.submission_blocked_reason !== null}
              isBusy={isBusy}
              onClick={() => void submit()}
            >
              Submit import
            </Button>
          </>
        }
      >
        {session.submission_blocked_reason ? (
          <p className={styles.notice}>{session.submission_blocked_reason}</p>
        ) : null}
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">Source columns and their mapped meaning</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Source column</th>
                <th scope="col">Means</th>
                <th scope="col">Origin</th>
                <th scope="col">Sampled values</th>
              </tr>
            </thead>
            <tbody>
              {session.mappings.map((mapping) => (
                <tr key={mapping.id}>
                  <td>{mapping.source_column_index}</td>
                  <td>{mapping.source_column_name}</td>
                  <td>
                    <label
                      className="visually-hidden"
                      htmlFor={`concept-${mapping.source_column_index}`}
                    >
                      Meaning of {mapping.source_column_name}
                    </label>
                    <select
                      id={`concept-${mapping.source_column_index}`}
                      className={styles.select}
                      value={choices[mapping.source_column_index] ?? mapping.target_concept}
                      onChange={(event) =>
                        setChoices((current) => ({
                          ...current,
                          [mapping.source_column_index]: event.target.value,
                        }))
                      }
                    >
                      {CONCEPTS.map((concept) => (
                        <option key={concept.value} value={concept.value}>
                          {concept.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {mapping.origin === "human_confirmed" ? "confirmed by a person" : "suggested"}
                  </td>
                  <td className={styles.semanticsAbsent}>
                    {mapping.sample_value_semantics.replace(/_/g, " ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {session.latest_validation ? (
        <Card title="Import validation" headingLevel={3}>
          <ValidationSummaryBadges run={session.latest_validation} />
          <ValidationRunDetail client={client} runId={session.latest_validation.id} />
        </Card>
      ) : null}
    </>
  );
}
