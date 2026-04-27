import { cn } from "@/lib/utils";

const COMPACT_LABEL_MAX_LENGTH = 22;
const DIGEST_TOKEN = /^[A-F0-9]{8}$/i;
const PAGE_TOKEN = /^P?(\d+)$/i;
const COMPANY_STOP_WORDS = new Set(["KB", "PROFILE", "EVIDENCE"]);

function toReadablePhrase(tokens: string[]) {
  const words = tokens.slice(0, 2).map((token) => {
    if (/^\d+$/.test(token)) return token;
    if (/^[A-Z0-9]{2,}$/.test(token) && /\d/.test(token)) return token.toUpperCase();
    return token.toLowerCase();
  });
  const phrase = words.join(" ");
  return phrase ? phrase.charAt(0).toUpperCase() + phrase.slice(1) : "";
}

function compactPrefixedCitation(
  prefix: "Tender" | "Company",
  rawTokens: string[],
) {
  const tokens = [...rawTokens];
  const pageMatch = tokens[0]?.match(PAGE_TOKEN);
  const pageLabel = pageMatch ? ` p.${pageMatch[1]}` : "";
  if (pageMatch) tokens.shift();
  if (tokens.length > 0 && DIGEST_TOKEN.test(tokens[tokens.length - 1])) {
    tokens.pop();
  }

  const words = tokens.filter((token) => {
    if (token.length === 0) return false;
    if (prefix === "Company") return !COMPANY_STOP_WORDS.has(token.toUpperCase());
    return true;
  });
  const phrase = toReadablePhrase(words);
  return phrase
    ? `${prefix}${pageLabel} · ${phrase}${words.length > 2 ? "…" : ""}`
    : `${prefix}${pageLabel}`;
}

function compactLongCitation(id: string) {
  const head = id.slice(0, 10);
  const tail = id.slice(-5);
  return `${head}…${tail}`;
}

function evidenceBadgeLabel(id: string) {
  const trimmed = id.trim();
  if (trimmed.length <= COMPACT_LABEL_MAX_LENGTH) return id;

  const tokens = trimmed.split(/[-_.]+/).filter(Boolean);
  const prefix = tokens[0]?.toUpperCase();
  if (prefix === "TENDER") {
    return compactPrefixedCitation("Tender", tokens.slice(1));
  }
  if (prefix === "COMPANY") {
    return compactPrefixedCitation("Company", tokens.slice(1));
  }
  return compactLongCitation(trimmed);
}

export function EvidenceBadge({
  id,
  className,
  onClick,
  title,
}: {
  id: string;
  className?: string;
  onClick?: () => void;
  /** Optional tooltip for truncated or long keys */
  title?: string;
}) {
  const label = evidenceBadgeLabel(id);
  const classes = cn(
    "inline-flex max-w-full items-center align-middle leading-normal",
    "rounded-full border border-border bg-card px-2 py-0.5 text-[11px] font-medium text-foreground shadow-sm",
    onClick &&
      "cursor-pointer hover:border-primary/50 hover:bg-primary/5 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
    className,
  );
  const content = <span className="max-w-[12rem] truncate">{label}</span>;

  if (onClick) {
    return (
      <button
        type="button"
        title={title ?? id}
        aria-label={`Open source for ${id}`}
        onClick={onClick}
        className={classes}
      >
        {content}
      </button>
    );
  }

  return (
    <span
      title={title ?? id}
      className={classes}
    >
      {content}
    </span>
  );
}
