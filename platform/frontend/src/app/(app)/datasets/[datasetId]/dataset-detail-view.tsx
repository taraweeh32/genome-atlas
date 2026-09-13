"use client";

/**
 * Dataset detail: versions, files, verification results, acceptance and imports.
 *
 * Everything shown here is the server's own answer. In particular
 * `acceptance_blocked_reason` is displayed verbatim rather than recomputed, so
 * the UI cannot disagree with the rule the accept endpoint will apply. A refusal
 * is stated plainly instead of being retried.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { DatasetVersionResponse, FileArtifactResponse } from "@/lib/data-types";
import styles from "../datasets.module.css";
import { ImportPanel } from "./import-panel";
import { UploadPanel } from "./upload-panel";
import { ValidationRunDetail, ValidationSummaryBadges } from "./validation-issues";

function text(value: string): string {
  return value.replace(/_/g, " ");
}

function fileState(artifact: FileArtifactResponse): string {
  if (artifact.quarantined_at) return "quarantined";
  if (artifact.is_retrievable) return "verified";
  return `${text(artifact.upload_state)} · scan ${text(artifact.scan_state)} · ${text(
    artifact.validation_state,
  )}`;
}

export function DatasetDetailView({ datasetId }: { datasetId: string }) {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const dataset = useApiResource(() => client.dataset(datasetId), [client, datasetId]);
  const versions = useApiResource(() => client.datasetVersions(datasetId), [client, datasetId]);
  const [importArtifactId, setImportArtifactId] = useState<string | null>(null);
  const [isBusy, setBusy] = useState(false);

  function reload() {
    dataset.reload();
    versions.reload();
  }

  async function act<T>(action: () => Promise<T>, failure: string, success: string) {
    setBusy(true);
    try {
      await action();
      publish({ tone: "success", title: success });
      reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: failure,
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
    } finally {
      setBusy(false);
    }
  }

  async function download(artifactId: string) {
    setBusy(true);
    try {
      const grant = await client.requestArtifactDownload(artifactId);
      window.open(grant.download_url, "_blank", "noopener");
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The download was refused",
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
    } finally {
      setBusy(false);
    }
  }

  if (dataset.status === "loading") {
    return (
      <Card title="Dataset">
        <LoadingState label="Loading dataset" />
      </Card>
    );
  }
  if (dataset.status === "error" || !dataset.data) {
    return (
      <Card title="Dataset">
        <ErrorState
          title={dataset.isForbidden ? "This dataset is not available to you" : undefined}
          description={dataset.error ?? undefined}
          correlationId={dataset.correlationId ?? undefined}
          action={dataset.isForbidden ? undefined : <Button onClick={reload}>Try again</Button>}
        />
      </Card>
    );
  }

  const record = dataset.data;
  const canWrite = record.capabilities.includes("write");
  const canImport = record.capabilities.includes("import");
  const canDownload = record.capabilities.includes("download");

  return (
    <>
      <Card
        title={record.name}
        description={record.description ?? undefined}
        actions={<Button onClick={reload}>Refresh</Button>}
      >
        <DefinitionList
          items={[
            { term: "Kind", value: text(record.kind) },
            { term: "State", value: text(record.state) },
            { term: "Declared build", value: text(record.reference_build_declared) },
            { term: "Versions", value: String(record.version_count) },
            {
              term: "Current input",
              value: record.current_version_id ?? "no version has been accepted",
            },
            { term: "Retention", value: text(record.deletion_state) },
          ]}
        />
        {canWrite ? (
          <Button
            isBusy={isBusy}
            onClick={() =>
              void act(
                () => client.createDatasetVersion(datasetId),
                "The version was not created",
                "New draft version created",
              )
            }
          >
            Start a new version
          </Button>
        ) : (
          <p className={styles.notice}>
            You may read this dataset but not change it. Controls you cannot use are not shown.
          </p>
        )}
      </Card>

      <Card title="Versions" description="A version is an immutable input once accepted.">
        {versions.status === "loading" ? (
          <LoadingState label="Loading versions" />
        ) : versions.status === "error" ? (
          <ErrorState
            description={versions.error ?? undefined}
            correlationId={versions.correlationId ?? undefined}
          />
        ) : versions.data && versions.data.items.length > 0 ? (
          <ul className={styles.list}>
            {versions.data.items.map((version) => (
              <li key={version.id}>
                <VersionRow
                  client={client}
                  version={version}
                  canWrite={canWrite}
                  canImport={canImport}
                  canDownload={canDownload}
                  isBusy={isBusy}
                  onDownload={(artifactId) => void download(artifactId)}
                  onImport={(artifactId) => setImportArtifactId(artifactId)}
                  onDecide={(accept) =>
                    void act(
                      () => client.decideDatasetVersion(version.id, { accept }),
                      accept ? "The version was not accepted" : "The version was not rejected",
                      accept ? "Version accepted as the current input" : "Version rejected",
                    )
                  }
                  onUploaded={reload}
                />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No versions yet"
            description="Start a version, then add the file it contains. Nothing is analysed until a version is verified and accepted."
          />
        )}
      </Card>

      {importArtifactId && canImport ? (
        <ImportPanel client={client} artifactId={importArtifactId} onChanged={reload} />
      ) : null}
    </>
  );
}

function VersionRow({
  client,
  version,
  canWrite,
  canImport,
  canDownload,
  isBusy,
  onDownload,
  onImport,
  onDecide,
  onUploaded,
}: {
  client: ApiClient;
  version: DatasetVersionResponse;
  canWrite: boolean;
  canImport: boolean;
  canDownload: boolean;
  isBusy: boolean;
  onDownload(artifactId: string): void;
  onImport(artifactId: string): void;
  onDecide(accept: boolean): void;
  onUploaded(): void;
}) {
  const accepted = version.state === "accepted";
  return (
    <Card
      title={`Version ${version.version_number}`}
      description={`${text(version.state)} · detected format ${text(version.detected_format)}`}
      headingLevel={3}
      actions={
        canWrite && !accepted ? (
          <>
            <Button
              variant="primary"
              disabled={version.acceptance_blocked_reason !== null}
              isBusy={isBusy}
              onClick={() => onDecide(true)}
            >
              Accept as current input
            </Button>
            <Button variant="danger" isBusy={isBusy} onClick={() => onDecide(false)}>
              Reject
            </Button>
          </>
        ) : undefined
      }
    >
      {version.acceptance_blocked_reason ? (
        <p className={styles.notice}>{version.acceptance_blocked_reason}</p>
      ) : null}
      {version.rejection_reason ? (
        <p className={styles.notice}>Rejected: {version.rejection_reason}</p>
      ) : null}

      {version.artifacts.length > 0 ? (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">Files in this version</caption>
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Size</th>
                <th scope="col">Format</th>
                <th scope="col">State</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {version.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <td>{artifact.filename}</td>
                  <td>{artifact.size_bytes === null ? "not known yet" : `${artifact.size_bytes} B`}</td>
                  <td>{text(artifact.detected_format)}</td>
                  <td>{fileState(artifact)}</td>
                  <td>
                    {artifact.is_retrievable && canDownload ? (
                      <Button size="sm" isBusy={isBusy} onClick={() => onDownload(artifact.id)}>
                        Download
                      </Button>
                    ) : null}
                    {artifact.is_retrievable && canImport ? (
                      <Button size="sm" onClick={() => onImport(artifact.id)}>
                        Import
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No file in this version yet" />
      )}

      {version.latest_validation ? (
        <>
          <ValidationSummaryBadges run={version.latest_validation} />
          <ValidationRunDetail client={client} runId={version.latest_validation.id} />
        </>
      ) : null}

      {canWrite ? (
        <UploadPanel
          client={client}
          versionId={version.id}
          disabledReason={
            accepted
              ? "This version is accepted and immutable. Start a new version to submit corrected data."
              : version.state === "rejected"
                ? "This version was rejected. Start a new version instead."
                : null
          }
          onUploaded={onUploaded}
        />
      ) : null}
    </Card>
  );
}
