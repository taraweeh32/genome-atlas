"use client";

/**
 * Organizations surface.
 *
 * Shows the organizations the backend says the caller reaches, the invitations
 * awaiting their response, and a request form. Every state transition (approval,
 * membership, invitation response) is executed and authorized by the backend.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { Field, authStyles as formStyles } from "@/components/auth/field";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";

export function OrganizationsView() {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const organizations = useApiResource(() => client.organizations(), [client]);
  const invitations = useApiResource(() => client.myInvitations(), [client]);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [token, setToken] = useState("");
  const [isBusy, setBusy] = useState(false);

  function report(cause: unknown, title: string) {
    const error = cause instanceof ApiError ? cause : null;
    publish({
      tone: "danger",
      title,
      description: error?.message ?? "The platform API could not be reached.",
      correlationId: error?.correlationId,
    });
  }

  async function requestOrganization(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await client.requestOrganization({ name, slug });
      publish({
        tone: "success",
        title: "Organization requested",
        description: `“${created.name}” is ${created.state.replace(/_/g, " ")}. A platform administrator decides the outcome.`,
      });
      setName("");
      setSlug("");
      organizations.reload();
    } catch (cause) {
      report(cause, "The organization request was refused");
    } finally {
      setBusy(false);
    }
  }

  async function respond(accept: boolean) {
    setBusy(true);
    try {
      await client.respondToInvitation(token, accept);
      publish({
        tone: "success",
        title: accept ? "Invitation accepted" : "Invitation declined",
      });
      setToken("");
      invitations.reload();
      organizations.reload();
    } catch (cause) {
      report(cause, "The invitation response was refused");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Card title="Your organizations">
        {organizations.status === "loading" ? (
          <LoadingState label="Loading organizations" />
        ) : organizations.status === "error" ? (
          <ErrorState
            description={organizations.error ?? undefined}
            correlationId={organizations.correlationId ?? undefined}
            action={<Button onClick={organizations.reload}>Try again</Button>}
          />
        ) : organizations.data && organizations.data.items.length > 0 ? (
          <ul>
            {organizations.data.items.map((organization) => (
              <li key={organization.id}>
                <DefinitionList
                  items={[
                    { term: "Name", value: organization.name },
                    { term: "Identifier", value: organization.slug },
                    { term: "State", value: organization.state.replace(/_/g, " ") },
                    { term: "Your role", value: organization.role ?? "none" },
                  ]}
                />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="You do not belong to an organization"
            description="This is a valid state: your personal workspace works without one."
          />
        )}
      </Card>

      <Card
        title="Invitations awaiting your response"
        description="An invitation is answered with its token, which the backend consumes once."
      >
        {invitations.status === "loading" ? (
          <LoadingState label="Loading invitations" />
        ) : invitations.status === "error" ? (
          <ErrorState
            description={invitations.error ?? undefined}
            correlationId={invitations.correlationId ?? undefined}
          />
        ) : invitations.data && invitations.data.items.length > 0 ? (
          <ul>
            {invitations.data.items.map((invitation) => (
              <li key={invitation.id}>
                Role <strong>{invitation.role}</strong>, expires{" "}
                {new Date(invitation.expires_at).toLocaleString()}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No invitations are waiting" />
        )}

        <div className={formStyles.form}>
          <Field
            id="invitation-token"
            label="Invitation token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <div className={formStyles.actions}>
            <Button variant="primary" isBusy={isBusy} onClick={() => void respond(true)}>
              Accept
            </Button>
            <Button isBusy={isBusy} onClick={() => void respond(false)}>
              Decline
            </Button>
          </div>
        </div>
      </Card>

      <Card
        title="Request an organization"
        description="Creation is a request. A platform administrator approves or rejects it, and the organization workspace is provisioned on approval."
      >
        <form className={formStyles.form} onSubmit={requestOrganization} noValidate>
          <Field
            id="organization-name"
            label="Organization name"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Field
            id="organization-slug"
            label="Identifier"
            required
            hint="Lower-case, stable, used in URLs. Uniqueness is enforced by the backend."
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
          />
          <div className={formStyles.actions}>
            <Button type="submit" variant="primary" isBusy={isBusy}>
              Submit request
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
