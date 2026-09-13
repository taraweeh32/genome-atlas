/**
 * Session context behaviour.
 *
 * The session is whatever the backend reports. These tests assert that the
 * context never invents an identity, treats 401 as the ordinary anonymous state,
 * distinguishes a transport failure from being signed out, and forgets the
 * identity on sign-out even if the backend call fails.
 */

import { describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { SessionProvider, useSession } from "@/context/session-context";
import { ApiError } from "@/lib/api-client";
import type { IdentityResponse } from "@/lib/identity-types";

const identity: IdentityResponse = {
  account: {
    id: "usr_1",
    email: "researcher@example.org",
    display_name: "Researcher",
    account_state: "active",
    email_verification_state: "verified",
    personal_workspace_id: "wsp_1",
    created_at: "2024-01-01T00:00:00Z",
  },
  session: {
    id: "ses_1",
    issued_at: "2024-01-01T00:00:00Z",
    expires_at: "2024-01-01T01:00:00Z",
    absolute_expires_at: "2024-01-01T12:00:00Z",
    last_seen_at: null,
    user_agent_summary: "test",
  },
  platform_roles: ["platform_administrator"],
  capabilities: ["platform.user.manage"],
  requires_reauthentication: false,
};

function Probe() {
  const session = useSession();
  return (
    <div>
      <span data-testid="status">{session.status}</span>
      <span data-testid="email">{session.identity?.account.email ?? "none"}</span>
      <span data-testid="can">{String(session.can("platform.user.manage"))}</span>
      <span data-testid="role">{String(session.hasPlatformRole("platform_administrator"))}</span>
      <span data-testid="error">{session.error ?? ""}</span>
      <button type="button" onClick={() => void session.signOut()}>
        sign out
      </button>
    </div>
  );
}

function clientStub(overrides: Record<string, unknown>) {
  return overrides as never;
}

describe("session context", () => {
  it("mirrors the identity the backend reports", async () => {
    render(
      <SessionProvider client={clientStub({ identity: vi.fn().mockResolvedValue(identity) })}>
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(screen.getByTestId("email").textContent).toBe("researcher@example.org");
    expect(screen.getByTestId("can").textContent).toBe("true");
    expect(screen.getByTestId("role").textContent).toBe("true");
  });

  it("treats an unauthenticated response as anonymous, not an error", async () => {
    render(
      <SessionProvider
        client={clientStub({
          identity: vi.fn().mockRejectedValue(new ApiError(401, "unauthorized", "Authentication is required.")),
        })}
      >
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(screen.getByTestId("email").textContent).toBe("none");
    expect(screen.getByTestId("error").textContent).toBe("");
  });

  it("distinguishes a transport failure from being signed out", async () => {
    render(
      <SessionProvider
        client={clientStub({ identity: vi.fn().mockRejectedValue(new Error("network down")) })}
      >
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("error"));
    expect(screen.getByTestId("email").textContent).toBe("none");
  });

  it("reports no capability while the session is unresolved", () => {
    render(
      <SessionProvider client={clientStub({ identity: vi.fn() })} loadOnMount={false}>
        <Probe />
      </SessionProvider>,
    );

    expect(screen.getByTestId("status").textContent).toBe("unknown");
    expect(screen.getByTestId("can").textContent).toBe("false");
    expect(screen.getByTestId("role").textContent).toBe("false");
  });

  it("forgets the identity on sign-out even when the backend call fails", async () => {
    const signOut = vi.fn().mockRejectedValue(new ApiError(503, "unavailable", "The service is unavailable."));
    render(
      <SessionProvider
        client={clientStub({ identity: vi.fn().mockResolvedValue(identity), signOut })}
      >
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));

    await act(async () => {
      screen.getByRole("button", { name: "sign out" }).click();
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(screen.getByTestId("email").textContent).toBe("none");
    expect(signOut).toHaveBeenCalledWith(false);
  });
});
