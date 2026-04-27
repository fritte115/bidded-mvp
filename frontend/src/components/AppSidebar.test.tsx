import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarProvider } from "@/components/ui/sidebar";

vi.mock("@/lib/auth", () => ({
  usePermissions: () => ({
    isSuperadmin: false,
    canRegisterProcurements: true,
    canStartRuns: true,
    canManageCompany: true,
    canManageBids: true,
    canDeleteProcurements: true,
    canDeleteRuns: true,
    canManageTeam: true,
  }),
}));

function renderSidebar(path = "/procurements") {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <SidebarProvider>
        <AppSidebar />
      </SidebarProvider>
    </MemoryRouter>,
  );
}

describe("AppSidebar", () => {
  it("links dashboard directly and keeps decisions out of the sidebar", () => {
    renderSidebar();

    expect(screen.queryByRole("link", { name: /compare/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /decisions/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /overview/i })).not.toBeInTheDocument();

    expect(screen.getByRole("link", { name: /dashboard/i })).toHaveAttribute("href", "/");
  });
});
