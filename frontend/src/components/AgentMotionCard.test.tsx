import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
});
