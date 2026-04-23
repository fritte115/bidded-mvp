import { describe, expect, it } from "vitest";

import { permissionsForRole } from "@/lib/auth";

describe("permissionsForRole", () => {
  it("keeps sensitive writes admin-only while allowing users to work", () => {
    const user = permissionsForRole("user");

    expect(user.canRegisterProcurements).toBe(true);
    expect(user.canStartRuns).toBe(true);
    expect(user.canManageCompany).toBe(false);
    expect(user.canManageBids).toBe(false);
    expect(user.canDeleteProcurements).toBe(false);
    expect(user.canDeleteRuns).toBe(false);
    expect(user.canManageTeam).toBe(false);
  });

  it("allows admins to manage company data, bids, deletes, and team access", () => {
    const admin = permissionsForRole("admin");

    expect(admin.canManageCompany).toBe(true);
    expect(admin.canManageBids).toBe(true);
    expect(admin.canDeleteProcurements).toBe(true);
    expect(admin.canDeleteRuns).toBe(true);
    expect(admin.canManageTeam).toBe(true);
  });

  it("treats superadmins as globally privileged", () => {
    expect(permissionsForRole("superadmin").isSuperadmin).toBe(true);
  });
});
