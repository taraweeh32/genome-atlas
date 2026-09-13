"use client";

/**
 * Platform administration panels: accounts and pending organization requests.
 *
 * Both surfaces are platform-scoped. When the caller is not a platform
 * administrator the backend refuses the request and the refusal is displayed —
 * the UI never simulates administrative data it was not given.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState, SkeletonRows } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { Field, authStyles as formStyles } from "@/components/auth/field";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import styles from "./administration.module.css";

const ACCOUNT_STATES = ["active", "suspended", "deactivated"] as const;

export function AdministrationView() {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const accounts = useApiResource(
    () => client.adminAccounts(appliedQuery ? { query: appliedQuery } : undefined),
    [client, appliedQuery],
  );
  const requests = useApiResource(() => client.adminOrganizationRequests(), [client]);
  const [busyId, setBusyId] = useState<string | null>(null);

  function report(cause: unknown, title: string) {
    const error = cause instanceof ApiError ? cause : null;
    publish({
      tone: "danger",
      title,
      description: error?.message ?? "The platform API could not be reached.",
      correlationId: error?.correlationId,
    });
  }

  async function changeState(userId: string, state: string) {
    const reason = window.prompt(
      `State the reason for setting this account to “${state}”. The reason is recorded in the audit trail.`,
    );
    if (reason === null) return;
    setBusyId(userId);
    try {
      await client.adminChangeAccountState(userId, { state, reason });
      publish({ tone: "success", title: `Account set to ${state}` });
      accounts.reload();
    } catch (cause) {
      report(cause, "The account state was not changed");
    } finally {
      setBusyId(null);
    }
  }

  async function decide(organizationId: string, approve: boolean) {
    const reason = window.prompt(
      approve
        ? "Optional note for the approval decision."
        : "State the reason for rejecting this organization request.",
    );
    if (reason === null) return;
    setBusyId(organizationId);
    try {
      await client.adminDecideOrganizationRequest(organizationId, { approve, reason });
      publish({
        tone: "success",
        title: approve ? "Organization approved" : "Organization request rejected",
      });
      requests.reload();
    } catch (cause) {
      report(cause, "The decision was refused");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <Card
        title="Organization requests awaiting review"
        description="Only a platform administrator may approve an organization. Approval provisions its workspace."
      >
        {requests.status === "loading" ? (
          <SkeletonRows rows={3} />
        ) : requests.status === "error" ? (
          <ErrorState
            title={
              requests.isForbidden
                ? "You are not permitted to review organization requests"
                : undefined
            }
            description={requests.error ?? undefined}
            correlationId={requests.correlationId ?? undefined}
            action={
              requests.isForbidden ? undefined : <Button onClick={requests.reload}>Try again</Button>
            }
          />
        ) : requests.data && requests.data.items.length > 0 ? (
          <table className={styles.table}>
            <caption className="visually-hidden">Pending organization requests</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Identifier</th>
                <th scope="col">State</th>
                <th scope="col">Requested</th>
                <th scope="col">Decision</th>
              </tr>
            </thead>
            <tbody>
              {requests.data.items.map((request) => (
                <tr key={request.id}>
                  <td>{request.name}</td>
                  <td>
                    <code>{request.slug}</code>
                  </td>
                  <td>{request.state.replace(/_/g, " ")}</td>
                  <td>
                    {request.requested_at
                      ? new Date(request.requested_at).toLocaleString()
                      : "unknown"}
                  </td>
                  <td className={styles.rowActions}>
                    <Button
                      size="sm"
                      variant="primary"
                      isBusy={busyId === request.id}
                      onClick={() => void decide(request.id, true)}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      isBusy={busyId === request.id}
                      onClick={() => void decide(request.id, false)}
                    >
                      Reject
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No organization requests are awaiting review" />
        )}
      </Card>

      <Card
        title="Accounts"
        description="Account lifecycle changes require a reason and are written to the audit trail."
      >
        <form
          className={formStyles.form}
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedQuery(query.trim());
          }}
          noValidate
        >
          <Field
            id="account-query"
            label="Search accounts"
            value={query}
            hint="Matches email address or display name. Filtering is performed by the backend."
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className={formStyles.actions}>
            <Button type="submit">Search</Button>
          </div>
        </form>

        {accounts.status === "loading" ? (
          <LoadingState label="Loading accounts" />
        ) : accounts.status === "error" ? (
          <ErrorState
            title={accounts.isForbidden ? "You are not permitted to manage accounts" : undefined}
            description={accounts.error ?? undefined}
            correlationId={accounts.correlationId ?? undefined}
            action={
              accounts.isForbidden ? undefined : <Button onClick={accounts.reload}>Try again</Button>
            }
          />
        ) : accounts.data && accounts.data.items.length > 0 ? (
          <table className={styles.table}>
            <caption className="visually-hidden">Platform accounts</caption>
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th scope="col">State</th>
                <th scope="col">Email verification</th>
                <th scope="col">Retention</th>
                <th scope="col">Lifecycle</th>
              </tr>
            </thead>
            <tbody>
              {accounts.data.items.map((account) => (
                <tr key={account.id}>
                  <td>
                    <span className={styles.primaryCell}>{account.display_name}</span>
                    <span className={styles.secondaryCell}>{account.email}</span>
                  </td>
                  <td>{account.account_state.replace(/_/g, " ")}</td>
                  <td>{account.email_verification_state.replace(/_/g, " ")}</td>
                  <td>{account.deletion_state.replace(/_/g, " ")}</td>
                  <td className={styles.rowActions}>
                    {ACCOUNT_STATES.filter((state) => state !== account.account_state).map(
                      (state) => (
                        <Button
                          key={state}
                          size="sm"
                          variant={state === "active" ? "secondary" : "danger"}
                          isBusy={busyId === account.id}
                          onClick={() => void changeState(account.id, state)}
                        >
                          {state}
                        </Button>
                      ),
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No accounts matched" />
        )}
      </Card>
    </>
  );
}
