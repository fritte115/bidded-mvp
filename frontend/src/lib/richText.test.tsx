import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderFormattedText } from "@/lib/richText";

describe("renderFormattedText", () => {
  it("italicizes Delivery CFO and Compliance Officer inside prose", () => {
    render(
      <p>
        {renderFormattedText(
          "Have Delivery CFO align with Compliance Officer before we do not bid.",
        )}
      </p>,
    );

    expect(screen.getByText("Delivery CFO").tagName).toBe("EM");
    expect(screen.getByText("Compliance Officer").tagName).toBe("EM");
    expect(screen.getByText("not bid").tagName).toBe("EM");
  });
});
