"use client";

/**
 * Variant browsing for one dataset version.
 *
 * The dataset version is the access path: the backend authorizes the version and
 * refuses variant reads outside the caller's scope, so this view never asks for a
 * variant without one. Contig and position bounds are passed to the server, which
 * performs the selection; no filtering or ranking happens in the browser.
 *
 * Every recorded context keeps its own attribution (imported, computed or human),
 * and an unreported value is displayed as unreported rather than as zero.
 */

import { useMemo, useState } from "react";
import { authStyles as formStyles } from "@/components/auth/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useWorkspace } from "@/context/workspace-context";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient } from "@/lib/api-client";
import type {
  AnnotationResponse,
  FrequencyResponse,
} from "@/lib/result-types";
import { ClassificationPanel } from "./classification-panel";
import { EvidencePanel } from "./evidence-panel";
import styles from "../results/results.module.css";

const EMPTY_PAGE = { items: [], page: { number: 1, size: 0, total: 0 } } as const;

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function unreported(semantics: string) {
  return <span className={styles.muted}>{label(semantics)}</span>;
}

/** Shows the value the resource reported, or its semantics when there is none. */
function annotationValue(annotation: AnnotationResponse): React.ReactNode {
  if (annotation.value_semantics !== "present") return unreported(annotation.value_semantics);
  if (annotation.value_string !== null) return annotation.value_string;
  if (annotation.value_number !== null) return annotation.value_number;
  if (annotation.value_integer !== null) return annotation.value_integer;
  if (annotation.value_boolean !== null) return annotation.value_boolean ? "true" : "false";
  if (annotation.value_json !== null) return JSON.stringify(annotation.value_json);
  return unreported(annotation.value_semantics);
}

function frequencyValue(frequency: FrequencyResponse): React.ReactNode {
  if (frequency.allele_frequency === null) return unreported(frequency.value_semantics);
  return frequency.allele_frequency;
}

export function VariantsView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const workspaceId = activeWorkspace?.id ?? null;

  const [datasetId, setDatasetId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [contig, setContig] = useState("");
  const [positionFrom, setPositionFrom] = useState("");
  const [positionTo, setPositionTo] = useState("");
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);

  const datasets = useApiResource(
    () =>
      workspaceId
        ? client.datasets({ workspace_id: workspaceId })
        : Promise.resolve(EMPTY_PAGE),
    [client, workspaceId],
  );

  const datasetOptions = datasets.data?.items ?? [];
  const selectedDataset = datasetId || datasetOptions[0]?.id || "";

  const versions = useApiResource(
    () =>
      selectedDataset
        ? client.datasetVersions(selectedDataset)
        : Promise.resolve(EMPTY_PAGE),
    [client, selectedDataset],
  );

  const versionOptions = versions.data?.items ?? [];
  const selectedVersion = versionId || versionOptions[0]?.id || "";

  const variants = useApiResource(
    () =>
      selectedVersion
        ? client.variants({
            dataset_version_id: selectedVersion,
            contig: contig.trim() === "" ? undefined : contig.trim(),
            position_from: positionFrom === "" ? undefined : Number(positionFrom),
            position_to: positionTo === "" ? undefined : Number(positionTo),
          })
        : Promise.resolve(EMPTY_PAGE),
    [client, selectedVersion, contig, positionFrom, positionTo],
  );

  const detail = useApiResource(
    () =>
      selectedVariantId && selectedVersion
        ? client.variant(selectedVariantId, selectedVersion)
        : Promise.resolve(null),
    [client, selectedVariantId, selectedVersion],
  );

  if (resolution !== "resolved" || !activeWorkspace) {
    return (
      <Card title="Workspace context">
        {resolution === "error" ? (
          <ErrorState description="Workspaces could not be loaded, so no variants can be listed." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  const detailData = detail.data;

  return (
    <>
      <Card
        title="Dataset version"
        description="Variants are read through a dataset version. Selecting one is an access path, not a filter: the backend authorizes the version on every request."
      >
        {datasetOptions.length === 0 ? (
          <EmptyState
            title="No dataset available"
            description="This workspace contains no dataset you may read, so no variant record can be reached."
          />
        ) : (
          <div className={styles.filters}>
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="variant-dataset">
                Dataset
              </label>
              <select
                id="variant-dataset"
                className={formStyles.input}
                value={selectedDataset}
                onChange={(event) => {
                  setDatasetId(event.target.value);
                  setVersionId("");
                  setSelectedVariantId(null);
                }}
              >
                {datasetOptions.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            </div>
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="variant-version">
                Version
              </label>
              <select
                id="variant-version"
                className={formStyles.input}
                value={selectedVersion}
                onChange={(event) => {
                  setVersionId(event.target.value);
                  setSelectedVariantId(null);
                }}
              >
                {versionOptions.map((version) => (
                  <option key={version.id} value={version.id}>
                    Version {version.version_number} · {label(version.state)}
                  </option>
                ))}
              </select>
            </div>
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="variant-contig">
                Contig
              </label>
              <input
                id="variant-contig"
                className={formStyles.input}
                value={contig}
                maxLength={64}
                onChange={(event) => setContig(event.target.value)}
              />
            </div>
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="variant-from">
                Position from
              </label>
              <input
                id="variant-from"
                type="number"
                min={0}
                className={formStyles.input}
                value={positionFrom}
                onChange={(event) => setPositionFrom(event.target.value)}
              />
            </div>
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="variant-to">
                Position to
              </label>
              <input
                id="variant-to"
                type="number"
                min={0}
                className={formStyles.input}
                value={positionTo}
                onChange={(event) => setPositionTo(event.target.value)}
              />
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Variant records"
        description="Canonical identity is genome build, contig, position and alleles under a stated normalization. A record whose normalization is unavailable is shown as such, never as normalized."
        actions={<Button onClick={variants.reload}>Refresh</Button>}
      >
        {!selectedVersion ? (
          <EmptyState
            title="No dataset version selected"
            description="Choose a dataset version to read the variants recorded against it."
          />
        ) : variants.status === "loading" ? (
          <LoadingState label="Loading variants" />
        ) : variants.status === "error" ? (
          <ErrorState
            description={variants.error ?? undefined}
            correlationId={variants.correlationId ?? undefined}
            action={
              variants.isForbidden ? undefined : (
                <Button onClick={variants.reload}>Try again</Button>
              )
            }
          />
        ) : variants.data && variants.data.items.length > 0 ? (
          <div className={styles.scroll}>
            <table className={`${styles.table} ${styles.dense}`}>
              <caption className="visually-hidden">
                Variants recorded for the selected dataset version
              </caption>
              <thead>
                <tr>
                  <th scope="col">Contig</th>
                  <th scope="col" className={styles.numeric}>
                    Position
                  </th>
                  <th scope="col">Ref</th>
                  <th scope="col">Alt</th>
                  <th scope="col">Class</th>
                  <th scope="col">Normalization</th>
                  <th scope="col">Origin</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {variants.data.items.map((variant) => (
                  <tr key={variant.id}>
                    <td>{variant.contig}</td>
                    <td className={styles.numeric}>{variant.position}</td>
                    <td>{variant.reference_allele}</td>
                    <td>{variant.alternate_allele}</td>
                    <td>{label(variant.variant_class)}</td>
                    <td>
                      <span className={styles.badge}>
                        {label(variant.normalization_state)}
                      </span>
                    </td>
                    <td>{label(variant.origin)}</td>
                    <td>
                      <Button
                        size="sm"
                        onClick={() => setSelectedVariantId(variant.id)}
                      >
                        Contexts
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No variants recorded"
            description="This dataset version has no variant record you may read. Records appear once the scientific subsystem has delivered them."
          />
        )}
      </Card>

      {selectedVariantId ? (
        <Card
          title="Recorded contexts"
          description="Each context keeps the resource, version and origin it came from. Nothing is merged, ranked or interpreted here."
          actions={<Button onClick={() => setSelectedVariantId(null)}>Close</Button>}
        >
          {detail.status === "loading" ? (
            <LoadingState label="Loading variant contexts" />
          ) : detail.status === "error" || !detailData ? (
            <ErrorState
              description={detail.error ?? undefined}
              correlationId={detail.correlationId ?? undefined}
              action={
                detail.isForbidden ? undefined : (
                  <Button onClick={detail.reload}>Try again</Button>
                )
              }
            />
          ) : (
            <>
              <dl className={styles.provenance}>
                <div>
                  <dt>Canonical key</dt>
                  <dd>{detailData.variant.canonical_key}</dd>
                </div>
                <div>
                  <dt>Reference genome resource</dt>
                  <dd>{detailData.variant.reference_genome_resource_id}</dd>
                </div>
                <div>
                  <dt>Normalization version</dt>
                  <dd>{detailData.variant.normalization_version}</dd>
                </div>
                <div>
                  <dt>Scientific execution</dt>
                  <dd>
                    {detailData.variant.scientific_execution_id ?? (
                      <span className={styles.muted}>not recorded</span>
                    )}
                  </dd>
                </div>
              </dl>

              <h3>Source representations</h3>
              {detailData.source_representations.length === 0 ? (
                <p className={styles.muted}>No source row is recorded.</p>
              ) : (
                <table className={`${styles.table} ${styles.dense}`}>
                  <caption className="visually-hidden">
                    Source representations preserved as submitted
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Record key</th>
                      <th scope="col">Contig</th>
                      <th scope="col" className={styles.numeric}>
                        Position
                      </th>
                      <th scope="col">Ref</th>
                      <th scope="col">Alt</th>
                      <th scope="col">Normalization</th>
                      <th scope="col">Unresolved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailData.source_representations.map((source) => (
                      <tr key={source.id}>
                        <td>{source.source_record_key}</td>
                        <td>{source.source_contig}</td>
                        <td className={styles.numeric}>{source.source_position}</td>
                        <td>{source.source_reference_allele ?? "—"}</td>
                        <td>{source.source_alternate_allele ?? "—"}</td>
                        <td>{label(source.normalization_state)}</td>
                        <td>
                          {source.is_unresolved ? (
                            <span className={styles.badge}>
                              {source.normalization_failure_reason ?? "unresolved"}
                            </span>
                          ) : (
                            <span className={styles.muted}>resolved</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h3>Annotations</h3>
              {detailData.annotations.length === 0 ? (
                <p className={styles.muted}>No annotation is recorded.</p>
              ) : (
                <table className={`${styles.table} ${styles.dense}`}>
                  <caption className="visually-hidden">Recorded annotations</caption>
                  <thead>
                    <tr>
                      <th scope="col">Field</th>
                      <th scope="col">Value</th>
                      <th scope="col">Resource</th>
                      <th scope="col">Resource version</th>
                      <th scope="col">Origin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailData.annotations.map((annotation) => (
                      <tr key={annotation.id}>
                        <td>{annotation.field_key}</td>
                        <td>{annotationValue(annotation)}</td>
                        <td>{annotation.annotation_resource_id}</td>
                        <td>{annotation.resource_version}</td>
                        <td>{label(annotation.origin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h3>Population frequencies</h3>
              {detailData.frequencies.length === 0 ? (
                <p className={styles.muted}>No frequency is recorded.</p>
              ) : (
                <table className={`${styles.table} ${styles.dense}`}>
                  <caption className="visually-hidden">Recorded frequencies</caption>
                  <thead>
                    <tr>
                      <th scope="col">Population</th>
                      <th scope="col" className={styles.numeric}>
                        Frequency
                      </th>
                      <th scope="col" className={styles.numeric}>
                        Allele count
                      </th>
                      <th scope="col" className={styles.numeric}>
                        Allele number
                      </th>
                      <th scope="col">Resource</th>
                      <th scope="col">Origin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailData.frequencies.map((frequency) => (
                      <tr key={frequency.id}>
                        <td>{frequency.population_id}</td>
                        <td className={styles.numeric}>{frequencyValue(frequency)}</td>
                        <td className={styles.numeric}>
                          {frequency.allele_count ?? unreported(frequency.value_semantics)}
                        </td>
                        <td className={styles.numeric}>
                          {frequency.allele_number ?? unreported(frequency.value_semantics)}
                        </td>
                        <td>
                          {frequency.population_resource_id} · {frequency.resource_version}
                        </td>
                        <td>{label(frequency.origin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h3>Transcript contexts</h3>
              {detailData.transcript_contexts.length === 0 ? (
                <p className={styles.muted}>No transcript context is recorded.</p>
              ) : (
                <table className={`${styles.table} ${styles.dense}`}>
                  <caption className="visually-hidden">Recorded transcript contexts</caption>
                  <thead>
                    <tr>
                      <th scope="col">Consequence</th>
                      <th scope="col">Transcript</th>
                      <th scope="col">Gene</th>
                      <th scope="col">Impact</th>
                      <th scope="col">HGVS c.</th>
                      <th scope="col">HGVS p.</th>
                      <th scope="col">Origin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailData.transcript_contexts.map((context) => (
                      <tr key={context.id}>
                        <td>{context.consequence_term}</td>
                        <td>{context.transcript_id ?? "—"}</td>
                        <td>{context.gene_id ?? "—"}</td>
                        <td>{context.impact ?? "—"}</td>
                        <td>{context.hgvs_coding ?? "—"}</td>
                        <td>{context.hgvs_protein ?? "—"}</td>
                        <td>{label(context.origin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h3>Clinical assertions</h3>
              {detailData.clinical_assertions.length === 0 ? (
                <p className={styles.muted}>No clinical assertion is recorded.</p>
              ) : (
                <table className={`${styles.table} ${styles.dense}`}>
                  <caption className="visually-hidden">Recorded clinical assertions</caption>
                  <thead>
                    <tr>
                      <th scope="col">Record</th>
                      <th scope="col">Reported classification</th>
                      <th scope="col">Condition</th>
                      <th scope="col">Submitter</th>
                      <th scope="col">Conflicts</th>
                      <th scope="col">Origin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailData.clinical_assertions.map((assertion) => (
                      <tr key={assertion.id}>
                        <td>{assertion.external_record_identifier}</td>
                        <td>
                          {assertion.reported_classification ??
                            unreported(assertion.value_semantics)}
                        </td>
                        <td>{assertion.condition_term ?? "—"}</td>
                        <td>{assertion.submitter ?? "—"}</td>
                        <td>
                          {Object.keys(assertion.conflict_information).length > 0 ? (
                            <span className={styles.badge}>recorded</span>
                          ) : (
                            <span className={styles.muted}>none reported</span>
                          )}
                        </td>
                        <td>{label(assertion.origin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h3>Sample observations</h3>
              {detailData.observations.length === 0 ? (
                <p className={styles.muted}>No sample observation is recorded.</p>
              ) : (
                <table className={`${styles.table} ${styles.dense}`}>
                  <caption className="visually-hidden">Recorded sample observations</caption>
                  <thead>
                    <tr>
                      <th scope="col">Sample</th>
                      <th scope="col">Zygosity</th>
                      <th scope="col">Genotype</th>
                      <th scope="col" className={styles.numeric}>
                        Depth
                      </th>
                      <th scope="col" className={styles.numeric}>
                        Alt depth
                      </th>
                      <th scope="col">Filter</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailData.observations.map((observation) => (
                      <tr key={observation.id}>
                        <td>{observation.sample_id}</td>
                        <td>{label(observation.zygosity)}</td>
                        <td>
                          {observation.genotype ??
                            unreported(observation.genotype_semantics)}
                        </td>
                        <td className={styles.numeric}>
                          {observation.read_depth ??
                            unreported(observation.genotype_semantics)}
                        </td>
                        <td className={styles.numeric}>
                          {observation.alternate_allele_depth ??
                            unreported(observation.genotype_semantics)}
                        </td>
                        <td>{observation.filter_status ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Card>
      ) : null}
      {selectedVariantId ? <EvidencePanel variantId={selectedVariantId} /> : null}
      {selectedVariantId ? <ClassificationPanel variantId={selectedVariantId} /> : null}
    </>
  );
}
