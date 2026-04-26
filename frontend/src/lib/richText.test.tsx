import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderFormattedText } from "@/lib/richText";

describe("renderFormattedText", () => {
  it("italicizes agent names inside prose", () => {
    render(
      <p>
        {renderFormattedText(
          "Have Delivery CFO align with Compliance Officer, Red Team, and Win Strategist before we do not bid.",
        )}
      </p>,
    );

    expect(screen.getByText("Delivery CFO").tagName).toBe("EM");
    expect(screen.getByText("Compliance Officer").tagName).toBe("EM");
    expect(screen.getByText("Red Team").tagName).toBe("EM");
    expect(screen.getByText("Win Strategist").tagName).toBe("EM");
    expect(screen.getByText("not bid").tagName).toBe("EM");
  });
});
