import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  JudgeVerdictSummary,
} from "@/components/JudgeVerdictSummary";
import { formatJudgeMemo } from "@/lib/judgeMemo";

const memo =
  "Acme should submit a CONDITIONAL BID. The opportunity is strategically aligned, but two contractual conditions must be resolved pre-submission: (1) clarification of unlimited liability for security incidents, and (2) a documented clearance plan with the customer. Margins are acceptable under a blended delivery model.";
const noBidMemo =
  "Acme should NOT bid. Healthcare domain depth is thin and the clinical safety classification adds delivery risk that is not offset by the contract value or strategic fit.";

describe("JudgeVerdictSummary", () => {
  it("turns the first judge memo sentence into a title and numbered items into a list", () => {
    const formatted = formatJudgeMemo(memo, "CONDITIONAL_BID");

    expect(formatted.title).toBe("Acme should submit a conditional bid.");
    expect(formatted.blocks).toContainEqual({
      type: "list",
      items: [
        "clarification of unlimited liability for security incidents",
        "a documented clearance plan with the customer.",
      ],
    });
  });

  it("renders the final verdict with a readable memo structure", () => {
    render(
      <JudgeVerdictSummary
        verdict="CONDITIONAL_BID"
        confidence={71}
        citedMemo={memo}
        voteSummary={{ BID: 1, NO_BID: 0, CONDITIONAL_BID: 3 }}
      />,
    );

    expect(screen.getByText("Final verdict")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
      "Acme should submit a conditional bid.",
    );
    expect(
      screen.getByText("clarification of unlimited liability for security incidents"),
    ).toBeInTheDocument();
    expect(screen.getByText("a documented clearance plan with the customer.")).toBeInTheDocument();
    expect(screen.getAllByText("Conditional bid").length).toBeGreaterThan(0);
    expect(screen.getByText("No bid")).toBeInTheDocument();
  });

  it("renders no-bid judge titles as plain prose with the action emphasized", () => {
    render(
      <JudgeVerdictSummary
        verdict="NO_BID"
        confidence={82}
        citedMemo={noBidMemo}
        voteSummary={{ BID: 0, NO_BID: 3, CONDITIONAL_BID: 1 }}
      />,
    );

    const heading = screen.getByRole("heading", { level: 3 });
    expect(heading).toHaveTextContent("Acme should not bid.");
    expect(heading).not.toHaveTextContent("NOT bid");
    expect(heading.querySelector("em")).toHaveTextContent("not bid");
  });
});
