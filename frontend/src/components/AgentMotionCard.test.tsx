import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentMotionCard } from "@/components/AgentMotionCard";
import type { AgentMotion } from "@/data/mock";

const baseMotion: AgentMotion = {
  agent: "Compliance Officer",
  verdict: "BID",
  confidence: 82,
  findings: ["The supplier meets the qualification requirements."],
};

describe("AgentMotionCard", () => {
  it("opts out of grid row stretching so only the opened card expands", () => {
    render(<AgentMotionCard motion={baseMotion} />);

    const card = screen.getByText("Compliance Officer").closest(".rounded-lg");

    expect(card).toHaveClass("self-start");
  });

  it("opens inline evidence citations through the passed click handler", async () => {
    const onCitationClick = vi.fn();
    render(
      <AgentMotionCard
        motion={{
          ...baseMotion,
          findings: ["The supplier meets EVD-004."],
        }}
        onCitationClick={onCitationClick}
      />,
    );

    fireEvent.click(screen.getByText("Compliance Officer"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open source for EVD-004" }),
    );

    expect(onCitationClick).toHaveBeenCalledWith("EVD-004");
  });
});
