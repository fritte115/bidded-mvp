/**
 * Maps Supabase `agent_outputs.validated_payload` JSON into UI `AgentMotion` models.
 * Supports strict LLM artifacts (Round1Motion / Round2Rebuttal) and routing-shell
 * state models (SpecialistMotionState / RebuttalState) with different field names.
 */

import type { AgentMotion, AgentMotionFinding, AgentName, Verdict } from "@/data/mock";

/** Normalize odd whitespace from PDF-derived or templated agent strings. */
export function normalizeMotionText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

export const AGENT_ROLE_LABELS: Record<string, AgentName> = {
  compliance_officer: "Compliance Officer",
  win_strategist: "Win Strategist",
  delivery_cfo: "Delivery CFO",
  red_team: "Red Team",
};

function normalizeVerdictStr(v: string): Verdict {
  return v.toUpperCase() as Verdict;
}

/** Extract evidence_key strings from API evidence_refs arrays (SupportedClaim, etc.). */
export function keysFromEvidenceRefs(refs: unknown): string[] {
  if (!Array.isArray(refs)) return [];
  const keys: string[] = [];
  for (const r of refs) {
    if (r && typeof r === "object" && "evidence_key" in r) {
      const k = (r as Record<string, unknown>).evidence_key;
      if (typeof k === "string" && k.length > 0) keys.push(k);
    }
  }
  return keys;
}

export function normalizeVoteToVerdict(voteRaw: unknown): Verdict {
  if (voteRaw == null || voteRaw === "") return normalizeVerdictStr("bid");
  if (typeof voteRaw === "string") return normalizeVerdictStr(voteRaw);
  if (typeof voteRaw === "object" && voteRaw !== null && "value" in voteRaw) {
    return normalizeVerdictStr(String((voteRaw as { value: string }).value));
  }
  return normalizeVerdictStr("bid");
}

function mapSupportedClaims(
  raw: unknown,
  prefix: string,
): AgentMotionFinding[] {
  if (!Array.isArray(raw)) return [];
  const out: AgentMotionFinding[] = [];
  for (const item of raw) {
    const fr = item as Record<string, unknown>;
    const claim = fr.claim as string | undefined;
    if (!claim) continue;
    const keys =
      (fr.evidence_keys as string[])?.filter((k) => typeof k === "string" && k.length > 0) ??
      keysFromEvidenceRefs(fr.evidence_refs);
    const text = normalizeMotionText(prefix ? `${prefix}${claim}` : claim);
    out.push({ claim: text, evidenceKeys: keys });
  }
  return out;
}

function appendStringLists(
  items: string[] | undefined,
  prefix: string,
  findings: string[],
  findingsWithEvidence: AgentMotionFinding[],
) {
  for (const s of items ?? []) {
    if (!s) continue;
    const claim = normalizeMotionText(prefix ? `${prefix}${s}` : s);
    findings.push(claim);
    findingsWithEvidence.push({ claim, evidenceKeys: [] });
  }
}

export function mapRound1Output(
  payload: Record<string, unknown>,
): AgentMotion | null {
  const role = payload.agent_role as string;
  const label = AGENT_ROLE_LABELS[role];
  if (!label) return null;

  const voteRaw = payload.vote ?? payload.verdict;
  const verdict = normalizeVoteToVerdict(voteRaw);

  const confidence = Math.round(((payload.confidence as number) ?? 0) * 100);

  const findings: string[] = [];
  const findingsWithEvidence: AgentMotionFinding[] = [];

  const topFindings = (payload.top_findings as unknown[]) ?? [];
  if (topFindings.length > 0) {
    const primary = mapSupportedClaims(topFindings, "");
    findings.push(...primary.map((f) => f.claim));
    findingsWithEvidence.push(...primary);

    const risks = mapSupportedClaims(payload.role_specific_risks, "Risk: ");
    findings.push(...risks.map((f) => f.claim));
    findingsWithEvidence.push(...risks);

    const formal = mapSupportedClaims(payload.formal_blockers, "Formal blocker: ");
    findings.push(...formal.map((f) => f.claim));
    findingsWithEvidence.push(...formal);

    const potential = mapSupportedClaims(payload.potential_blockers, "Potential blocker: ");
    findings.push(...potential.map((f) => f.claim));
    findingsWithEvidence.push(...potential);
  } else {
    const motionFindings = (payload.findings as string[]) ?? [];
    const motionKeys = keysFromEvidenceRefs(payload.evidence_refs);
    if (motionFindings.length > 0) {
      for (const claim of motionFindings) {
        const c = normalizeMotionText(claim);
        findings.push(c);
        findingsWithEvidence.push({ claim: c, evidenceKeys: motionKeys });
      }
    } else {
      const summary = payload.summary as string | undefined;
      if (summary) {
        const s = normalizeMotionText(summary);
        findings.push(s);
        findingsWithEvidence.push({ claim: s, evidenceKeys: motionKeys });
      }
    }
    appendStringLists(payload.risks as string[] | undefined, "Risk: ", findings, findingsWithEvidence);
    appendStringLists(
      payload.blockers as string[] | undefined,
      "Blocker: ",
      findings,
      findingsWithEvidence,
    );
  }

  appendStringLists(
    payload.assumptions as string[] | undefined,
    "Assumption: ",
    findings,
    findingsWithEvidence,
  );
  appendStringLists(
    payload.missing_info as string[] | undefined,
    "Missing info: ",
    findings,
    findingsWithEvidence,
  );
  appendStringLists(
    payload.potential_evidence_gaps as string[] | undefined,
    "Evidence gap: ",
    findings,
    findingsWithEvidence,
  );
  appendStringLists(
    payload.recommended_actions as string[] | undefined,
    "Recommended action: ",
    findings,
    findingsWithEvidence,
  );

  return {
    agent: label,
    verdict,
    confidence,
    findings,
    findingsWithEvidence,
  };
}

export function mapRound2Output(
  payload: Record<string, unknown>,
  round1MotionMap: Map<string, AgentMotion>,
): AgentMotion | null {
  const role = payload.agent_role as string;
  const label = AGENT_ROLE_LABELS[role];
  if (!label) return null;
  const prior = round1MotionMap.get(role);

  const revisedRaw = payload.revised_stance;
  let revisedVote: string | null = null;
  if (typeof revisedRaw === "string") revisedVote = revisedRaw;
  else if (revisedRaw && typeof revisedRaw === "object") {
    revisedVote =
      ((revisedRaw as Record<string, unknown>).vote as string | undefined) ?? null;
  }

  const verdict = revisedVote
    ? normalizeVoteToVerdict(revisedVote)
    : (prior?.verdict ?? "BID");

  const confidence =
    typeof payload.confidence === "number"
      ? Math.round((payload.confidence as number) * 100)
      : (prior?.confidence ?? 50);

  const hasRound2Artifact =
    Array.isArray(payload.target_roles) &&
    (payload.target_roles as unknown[]).length > 0;

  if (hasRound2Artifact) {
    const findings: string[] = [];
    const findingsWithEvidence: AgentMotionFinding[] = [];

    for (const d of (payload.targeted_disagreements as unknown[]) ?? []) {
      const dr = d as Record<string, unknown>;
      const rebuttal = dr.rebuttal as string | undefined;
      const keys = keysFromEvidenceRefs(dr.evidence_refs);
      if (rebuttal) {
        const line = normalizeMotionText(rebuttal);
        findings.push(line);
        findingsWithEvidence.push({ claim: line, evidenceKeys: keys });
      }
    }

    for (const uc of (payload.unsupported_claims as unknown[]) ?? []) {
      const u = uc as Record<string, unknown>;
      const claim = normalizeMotionText(
        `Unsupported claim: ${u.claim as string} (${u.reason as string})`,
      );
      findings.push(claim);
      findingsWithEvidence.push({ claim, evidenceKeys: [] });
    }

    for (const bc of (payload.blocker_challenges as unknown[]) ?? []) {
      const b = bc as Record<string, unknown>;
      const claim = normalizeMotionText(
        `Blocker (${String(b.position)}): ${b.blocker as string} — ${b.rationale as string}`,
      );
      findings.push(claim);
      findingsWithEvidence.push({
        claim,
        evidenceKeys: keysFromEvidenceRefs(b.evidence_refs),
      });
    }

    appendStringLists(
      payload.missing_info as string[] | undefined,
      "Missing info: ",
      findings,
      findingsWithEvidence,
    );
    appendStringLists(
      payload.recommended_actions as string[] | undefined,
      "Recommended action: ",
      findings,
      findingsWithEvidence,
    );

    const disagreements = (payload.targeted_disagreements as unknown[]) ?? [];
    const challenges = disagreements.map((d) =>
      normalizeMotionText((d as Record<string, unknown>).disputed_claim as string),
    );
    const challengesWithEvidence = disagreements.map((d) => {
      const dr = d as Record<string, unknown>;
      return {
        claim: normalizeMotionText(dr.disputed_claim as string),
        evidenceKeys: keysFromEvidenceRefs(dr.evidence_refs),
      };
    });

    const rebuttalFocus = ((payload.target_roles as string[]) ?? []).map(
      (r) => AGENT_ROLE_LABELS[r] ?? r,
    ) as AgentName[];

    if (findings.length === 0) {
      const fallback = "No rebuttal narrative was recorded in this audit payload.";
      findings.push(fallback);
      findingsWithEvidence.push({ claim: fallback, evidenceKeys: [] });
    }

    return {
      agent: label,
      verdict,
      confidence,
      findings,
      findingsWithEvidence,
      rebuttalFocus,
      challenges,
      challengesWithEvidence,
    };
  }

  const summary = normalizeMotionText((payload.summary as string) ?? "");
  const challenged = (payload.challenged_claims as string[]) ?? [];
  const accepted = (payload.accepted_claims as string[]) ?? [];
  const keys = keysFromEvidenceRefs(payload.evidence_refs);

  const findings: string[] = [];
  if (summary) findings.push(summary);
  for (const c of challenged)
    findings.push(normalizeMotionText(`Disputed: ${c}`));
  for (const a of accepted)
    findings.push(normalizeMotionText(`Accepted: ${a}`));

  if (findings.length === 0) {
    findings.push("No rebuttal narrative was recorded in this audit payload.");
  }

  const findingsWithEvidence = findings.map((claim) => ({
    claim,
    evidenceKeys: keys,
  }));

  const targetRole = payload.target_motion_role as string | undefined;
  const rebuttalFocus = targetRole
    ? ([AGENT_ROLE_LABELS[targetRole] ?? targetRole] as AgentName[])
    : undefined;

  return {
    agent: label,
    verdict: prior?.verdict ?? "BID",
    confidence: prior?.confidence ?? 50,
    findings,
    findingsWithEvidence,
    rebuttalFocus,
    challenges: challenged,
    challengesWithEvidence: challenged.map((c) => ({
      claim: c,
      evidenceKeys: keys,
    })),
  };
}
