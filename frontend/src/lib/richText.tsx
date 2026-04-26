import { Fragment, type ReactNode } from "react";
import { humanizeVerdictText } from "@/data/mock";

const EMPHASIZED_TOKENS =
  /(Compliance Officer|Delivery CFO|Red Team|Win Strategist|\bnot bid\b)/gi;
const ITALIC_AGENT_NAMES = new Set([
  "Compliance Officer",
  "Delivery CFO",
  "Red Team",
  "Win Strategist",
]);

export function renderFormattedText(text: string): ReactNode {
  const normalized = humanizeVerdictText(text);

  return normalized.split(EMPHASIZED_TOKENS).map((part, index) => {
    if (part === "") return null;

    if (/^not bid$/i.test(part)) {
      return (
        <em key={index} className="font-medium">
          not bid
        </em>
      );
    }

    if (ITALIC_AGENT_NAMES.has(part)) {
      return (
        <em key={index} className="font-medium">
          {part}
        </em>
      );
    }

    return <Fragment key={index}>{part}</Fragment>;
  });
}
