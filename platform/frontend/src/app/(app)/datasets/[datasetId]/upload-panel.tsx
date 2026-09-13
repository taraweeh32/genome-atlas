"use client";

/**
 * Upload panel for one dataset version.
 *
 * The transfer is a three-step protocol, and the UI is not authoritative in any
 * of them:
 *
 * 1. Ask the backend for an upload session and a short-lived transfer grant.
 * 2. Send the bytes straight to object storage with that grant — never through
 *    the platform API.
 * 3. Declare the transfer finished. The backend then queues durable verification
 *    (scan, inspection, checksum, structural validation) and can still refuse the
 *    artifact after its bytes exist.
 *
 * The digest is computed in the browser purely so the server can compare it with
 * what it actually stored. It is a claim, checked server-side, never trusted.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToasts } from "@/components/ui/toast";
import { ApiClient, ApiError } from "@/lib/api-client";
import styles from "../datasets.module.css";

/** Above this size the digest is not computed client-side; the server still verifies the stored bytes. */
const CLIENT_DIGEST_LIMIT_BYTES = 64 * 1024 * 1024;

async function sha256Hex(file: Blob): Promise<string | null> {
  if (file.size > CLIENT_DIGEST_LIMIT_BYTES) return null;
  if (typeof crypto === "undefined" || !crypto.subtle) return null;
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function UploadPanel({
  client,
  versionId,
  disabledReason,
  onUploaded,
}: {
  client: ApiClient;
  versionId: string;
  /** Non-null means the server's state for this version does not allow uploads. */
  disabledReason: string | null;
  onUploaded(): void;
}) {
  const { publish } = useToasts();
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<"idle" | "granting" | "transferring" | "completing">("idle");

  async function upload() {
    if (!file) return;
    try {
      setStage("granting");
      const checksum = await sha256Hex(file);
      const ticket = await client.openUploadSession(versionId, {
        filename: file.name,
        size_bytes: file.size,
        checksum_algorithm: "sha256",
        checksum_value: checksum,
        content_type: file.type || null,
      });
      setStage("transferring");
      await client.transferBytes(ticket.upload_url, file, file.type || undefined);
      setStage("completing");
      const session = await client.completeUpload(ticket.session.id);
      publish({
        tone: "success",
        title: "Transfer recorded",
        description:
          session.duplicate_relation !== "none"
            ? "The platform reports this file as a duplicate of an existing artifact. It was not merged or reused — review it and decide."
            : "Verification has been queued. The file is not usable until it passes.",
      });
      setFile(null);
      onUploaded();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The upload was not accepted",
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
    } finally {
      setStage("idle");
    }
  }

  return (
    <Card
      title="Add a file to this version"
      description="Bytes go directly to object storage using a short-lived grant. Holding a grant does not make a file usable: verification runs afterwards and can refuse it."
      headingLevel={3}
    >
      {disabledReason ? (
        <p className={styles.notice}>{disabledReason}</p>
      ) : (
        <>
          <input
            type="file"
            aria-label="File to upload"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <p className={styles.notice}>
            {stage === "granting"
              ? "Requesting a transfer grant…"
              : stage === "transferring"
                ? "Transferring to storage…"
                : stage === "completing"
                  ? "Declaring the transfer finished and queuing verification…"
                  : "Nothing is accepted until the platform has scanned, inspected and checksummed the stored bytes."}
          </p>
          <Button
            variant="primary"
            disabled={!file}
            isBusy={stage !== "idle"}
            onClick={() => void upload()}
          >
            Upload file
          </Button>
        </>
      )}
    </Card>
  );
}
