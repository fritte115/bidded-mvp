import { humanizeVerdictText, type Verdict } from "@/data/mock";

export type MemoBlock =
  | { type: "paragraph"; text: string }
  | { type: "list"; items: string[] };

export function formatJudgeMemo(
  memo: string,
  verdict: Verdict,
): { title: string; blocks: MemoBlock[] } {
  const sentences = splitSentences(memo);
  const fallbackTitle = `${verdictLabel(verdict)} recommended`;
  if (sentences.length === 0) {
    return {
      title: fallbackTitle,
      blocks: [{ type: "paragraph", text: "No judge memo recorded." }],
    };
  }

  const [title, ...bodySentences] = sentences;
  return {
    title: title || fallbackTitle,
    blocks: bodySentences.flatMap(blocksFromSentence),
  };
}

export function isDuplicateJudgeDisagreement(
  disagreement: string,
  memo: string,
): boolean {
  const normalizedDisagreement = normalizeComparableText(disagreement);
  const normalizedMemo = normalizeComparableText(memo);

  if (normalizedDisagreement.length === 0 || normalizedMemo.length === 0) {
    return false;
  }

  if (normalizedDisagreement === normalizedMemo) {
    return true;
  }

  if (isContainedDuplicate(normalizedDisagreement, normalizedMemo)) {
    return true;
  }

  return similarityRatio(normalizedDisagreement, normalizedMemo) >= 0.86;
}

function blocksFromSentence(sentence: string): MemoBlock[] {
  const list = numberedListFromSentence(sentence);
  if (!list) return [{ type: "paragraph", text: sentence }];

  const blocks: MemoBlock[] = [];
  if (list.intro) blocks.push({ type: "paragraph", text: list.intro });
  blocks.push({ type: "list", items: list.items });
  return blocks;
}

function numberedListFromSentence(
  sentence: string,
): { intro: string; items: string[] } | null {
  const matches = Array.from(
    sentence.matchAll(
      /\((\d+)\)\s*([\s\S]*?)(?=,\s*(?:and\s*)?\(\d+\)|\s+\(\d+\)|$)/g,
    ),
  );
  if (matches.length < 2 || matches[0].index == null) return null;

  const intro = sentence
    .slice(0, matches[0].index)
    .replace(/:\s*$/, "")
    .trim();
  const items = matches
    .map((match) => cleanSentence(match[2]))
    .filter((item) => item.length > 0);

  return items.length > 0 ? { intro, items } : null;
}

function splitSentences(text: string): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  return (
    normalized
      .match(/[^.!?]+[.!?]+(?:["')\]]+)?|[^.!?]+$/g)
      ?.map(cleanSentence)
      .filter(Boolean) ?? []
  );
}

function normalizeComparableText(text: string): string {
  return humanizeVerdictText(text)
    .replace(/\s+/g, " ")
    .replace(/[.!?]+$/g, "")
    .trim()
    .toLowerCase();
}

function isContainedDuplicate(left: string, right: string): boolean {
  const [shorter, longer] =
    left.length <= right.length ? [left, right] : [right, left];
  return (
    shorter.length >= 80 &&
    shorter.length / longer.length >= 0.72 &&
    longer.includes(shorter)
  );
}

function similarityRatio(left: string, right: string): number {
  const maxLength = Math.max(left.length, right.length);
  if (maxLength === 0) return 1;
  return 1 - levenshteinDistance(left, right) / maxLength;
}

function levenshteinDistance(left: string, right: string): number {
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);

  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const cost = left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1;
      current[rightIndex] = Math.min(
        current[rightIndex - 1] + 1,
        previous[rightIndex] + 1,
        previous[rightIndex - 1] + cost,
      );
    }
    previous = current;
  }

  return previous[right.length];
}

function cleanSentence(text: string): string {
  return humanizeVerdictText(text)
    .replace(/^\s*(?:and\s+)?/i, "")
    .replace(/\s+/g, " ")
    .replace(/[,\s]+$/g, "")
    .trim();
}

function verdictLabel(verdict: Verdict): string {
  return verdict === "CONDITIONAL_BID"
    ? "Conditional bid"
    : verdict === "NO_BID"
      ? "No bid"
      : "Bid";
}
