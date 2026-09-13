"use client";

/**
 * Registration form.
 *
 * Registration never establishes a session: the backend creates an unverified
 * account, provisions its personal workspace and issues a verification token.
 * The acknowledgement is deliberately identical whether or not the address is
 * already registered, so this form cannot be used to enumerate accounts.
 */

import Link from "next/link";
import { useState } from "react";
import { Field, authStyles as styles } from "./field";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { AcknowledgementResponse } from "@/lib/identity-types";

const MIN_PASSWORD_LENGTH = 12;

export function RegisterForm({ client }: { client?: ApiClient }) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [isBusy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ message: string; correlationId?: string } | null>(null);
  const [acknowledgement, setAcknowledgement] = useState<AcknowledgementResponse | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      const api = client ?? new ApiClient();
      setAcknowledgement(
        await api.register({ email, password, display_name: displayName }),
      );
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

  if (acknowledgement) {
    return (
      <div className={styles.form}>
        <p>{acknowledgement.message}</p>
        {acknowledgement.development_only_token ? (
          <p className={styles.token}>
            Development environment only — verification token:{" "}
            <code>{acknowledgement.development_only_token}</code>
          </p>
        ) : null}
        <p className={styles.links}>
          <Link href="/verify">Enter a verification token</Link>
          <Link href="/login">Sign in</Link>
        </p>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {failure ? (
        <ErrorState
          title="Registration was refused"
          description={failure.message}
          correlationId={failure.correlationId}
        />
      ) : null}
      <Field
        id="display-name"
        label="Display name"
        autoComplete="name"
        required
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
      />
      <Field
        id="email"
        label="Email address"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        id="password"
        label="Password"
        type="password"
        autoComplete="new-password"
        required
        minLength={MIN_PASSWORD_LENGTH}
        hint={`At least ${MIN_PASSWORD_LENGTH} characters. Password strength is enforced by the backend.`}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <div className={styles.actions}>
        <Button type="submit" variant="primary" isBusy={isBusy}>
          Create account
        </Button>
      </div>
      <p className={styles.links}>
        <Link href="/login">Already have an account</Link>
      </p>
    </form>
  );
}
