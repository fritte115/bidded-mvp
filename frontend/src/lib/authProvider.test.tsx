import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("AuthProvider local mock mode", () => {
  afterEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
  });

  it("creates a local demo workspace when Supabase env is missing outside production", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");

    const { AuthProvider, useAuth } = await import("@/lib/auth");

    function Probe() {
      const { displayName, error, loading, organizationName, role, user } = useAuth();

      return (
        <dl>
          <dt>loading</dt>
          <dd data-testid="loading">{loading ? "loading" : "ready"}</dd>
          <dt>email</dt>
          <dd data-testid="email">{user?.email ?? "missing"}</dd>
          <dt>role</dt>
          <dd data-testid="role">{role ?? "missing"}</dd>
          <dt>organization</dt>
          <dd data-testid="organization">{organizationName ?? "missing"}</dd>
          <dt>display name</dt>
          <dd data-testid="display-name">{displayName ?? "missing"}</dd>
          <dt>error</dt>
          <dd data-testid="error">{error ?? "none"}</dd>
        </dl>
      );
    }

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("ready");
    });
    expect(screen.getByTestId("email")).toHaveTextContent("demo@bidded.local");
    expect(screen.getByTestId("role")).toHaveTextContent("admin");
    expect(screen.getByTestId("organization")).toHaveTextContent("Bidded Demo");
    expect(screen.getByTestId("display-name")).toHaveTextContent("Demo Operator");
    expect(screen.getByTestId("error")).toHaveTextContent("none");
  });
});
