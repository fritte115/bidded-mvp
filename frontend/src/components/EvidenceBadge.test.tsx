import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EvidenceBadge } from "@/components/EvidenceBadge";

describe("EvidenceBadge", () => {
  it("renders clickable citations as accessible buttons", () => {
    const onClick = vi.fn();

    render(<EvidenceBadge id="EVD-001" onClick={onClick} />);

    const button = screen.getByRole("button", { name: "Open source for EVD-001" });
    fireEvent.click(button);

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("shows long tender citation keys as compact readable labels", () => {
    const id = "TENDER-2-SUBMISSION-DEADLINE-APPENDIX-A-ABCDEF12";

    render(<EvidenceBadge id={id} />);

    const badge = screen.getByTitle(id);

    expect(badge).toHaveTextContent("Tender p.2 · Submission deadline…");
    expect(screen.queryByText(id)).not.toBeInTheDocument();
  });
});
