"use client";

/**
 * Email-verification form.
 *
 * The token is validated by the backend, which consumes it exactly once. The
 * frontend only reports the outcome and, when the account had pending
 * organization invitations, says how many are waiting.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Field, authStyles as styles } from "./field";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { VerifyEmailResponse } from "@/lib/identity-types";

export function VerifyForm({ client }: { client?: ApiClient }) {
  const search = useSearchParams();
  const [token, setToken] = useState("");
  const [isBusy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ message: string; correlationId?: string } | null>(null);
  const [outcome, setOutcome] = useState<VerifyEmailResponse | null>(null);

  useEffect(() => {
    const supplied = search?.get("token");
    if (supplied) setToken(supplied);
  }, [search]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      const api = client ?? new ApiClient();
      setOutcome(await api.verifyEmail(token));
    } catch (cause) {
      setFailure({
        message:
          cause instanceof ApiError
            ? cause.message
            : "The platform API could not be reached. Try again shortly.",
        correlationId: cause instanceof ApiError ? cause.correlationId : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  if (outcome?.verified) {
    return (
      <div className={styles.form}>
        <p>Your email address is verified. You can sign in now.</p>
        {outcome.pending_invitation_count > 0 ? (
          <p className={styles.hint}>
            {outcome.pending_invitation_count} organization invitation
            {outcome.pending_invitation_count === 1 ? "" : "s"} are waiting for your response.
          </p>
        ) : null}
        <p className={styles.links}>
          <Link href="/login">Sign in</Link>
        </p>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {failure ? (
        <ErrorState
          title="Verification failed"
          description={failure.message}
          correlationId={failure.correlationId}
        />
      ) : null}
      <Field
        id="token"
        label="Verification token"
        required
        value={token}
        hint="Tokens are single-use and expire. Request a new one if this fails."
        onChange={(event) => setToken(event.target.value)}
      />
      <div className={styles.actions}>
        <Button type="submit" variant="primary" isBusy={isBusy}>
          Verify email
        </Button>
      </div>
      <p className={styles.links}>
        <Link href="/login">Sign in</Link>
      </p>
    </form>
  );
}
