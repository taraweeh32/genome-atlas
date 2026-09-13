"use client";

/**
 * Account recovery.
 *
 * Two steps, both backend-owned: requesting a reset (answered identically for
 * every address, so accounts cannot be enumerated) and completing it with the
 * single-use token, which revokes every existing session for that account.
 */

import Link from "next/link";
import { useState } from "react";
import { Field, authStyles as styles } from "./field";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { AcknowledgementResponse } from "@/lib/identity-types";

const MIN_PASSWORD_LENGTH = 12;

type Failure = { message: string; correlationId?: string } | null;

function describe(cause: unknown): Failure {
  return {
    message:
      cause instanceof ApiError
        ? cause.message
        : "The platform API could not be reached. Try again shortly.",
    correlationId: cause instanceof ApiError ? cause.correlationId : undefined,
  };
}

export function RecoverForm({ client }: { client?: ApiClient }) {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [isBusy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure>(null);
  const [acknowledgement, setAcknowledgement] = useState<AcknowledgementResponse | null>(null);
  const [completed, setCompleted] = useState(false);

  const api = () => client ?? new ApiClient();

  async function requestReset(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      setAcknowledgement(await api().requestPasswordReset(email));
    } catch (cause) {
      setFailure(describe(cause));
    } finally {
      setBusy(false);
    }
  }

  async function completeReset(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await api().completePasswordReset(token, password);
      setCompleted(true);
    } catch (cause) {
      setFailure(describe(cause));
    } finally {
      setBusy(false);
    }
  }

  if (completed) {
    return (
      <div className={styles.form}>
        <p>
          Your password has been replaced and every existing session for the account has been
          revoked. Sign in with the new password.
        </p>
        <p className={styles.links}>
          <Link href="/login">Sign in</Link>
        </p>
      </div>
    );
  }

  return (
    <div className={styles.form}>
      {failure ? (
        <ErrorState
          title="The request was refused"
          description={failure.message}
          correlationId={failure.correlationId}
        />
      ) : null}

      <form className={styles.form} onSubmit={requestReset} noValidate>
        <Field
          id="recover-email"
          label="Email address"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <div className={styles.actions}>
          <Button type="submit" isBusy={isBusy}>
            Send a reset token
          </Button>
        </div>
      </form>

      {acknowledgement ? (
        <>
          <p className={styles.hint}>{acknowledgement.message}</p>
          {acknowledgement.development_only_token ? (
            <p className={styles.token}>
              Development environment only — reset token:{" "}
              <code>{acknowledgement.development_only_token}</code>
            </p>
          ) : null}
        </>
      ) : null}

      <form className={styles.form} onSubmit={completeReset} noValidate>
        <Field
          id="recover-token"
          label="Reset token"
          required
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <Field
          id="recover-password"
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters. Strength is enforced by the backend.`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <div className={styles.actions}>
          <Button type="submit" variant="primary" isBusy={isBusy}>
            Set the new password
          </Button>
        </div>
      </form>

      <p className={styles.links}>
        <Link href="/login">Sign in</Link>
      </p>
    </div>
  );
}
