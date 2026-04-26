export type ProcurementDocumentRole =
  | "main_tender"
  | "qualification_appendix"
  | "evaluation_model"
  | "requirements_appendix"
  | "contract_terms"
  | "pricing_appendix"
  | "dpa";

export const PROCUREMENT_DOCUMENT_ROLE_OPTIONS: Array<{
  value: ProcurementDocumentRole;
  label: string;
}> = [
  { value: "main_tender", label: "Main tender" },
  { value: "qualification_appendix", label: "Qualification appendix" },
  { value: "evaluation_model", label: "Evaluation model" },
  { value: "requirements_appendix", label: "Requirements appendix" },
  { value: "contract_terms", label: "Contract terms" },
  { value: "pricing_appendix", label: "Pricing appendix" },
  { value: "dpa", label: "DPA" },
];

export function inferProcurementDocumentRole(
  filename: string,
  options?: { isFirstDocument?: boolean },
): ProcurementDocumentRole | null {
  const isFirstDocument = options?.isFirstDocument ?? false;
  const lowered = filename.trim().toLowerCase();
  if (!lowered) {
    return isFirstDocument ? "main_tender" : null;
  }
  if (
    lowered.includes("pricing") ||
    lowered.includes("price") ||
    lowered.includes("pris")
  ) {
    return "pricing_appendix";
  }
  if (
    lowered.includes("dpa") ||
    lowered.includes("data processing") ||
    lowered.includes("personuppgift") ||
    lowered.includes("dataskydd")
  ) {
    return "dpa";
  }
  if (
    lowered.includes("evaluation") ||
    lowered.includes("award") ||
    lowered.includes("utvarder") ||
    lowered.includes("utvärder")
  ) {
    return "evaluation_model";
  }
  if (
    lowered.includes("qualification") ||
    lowered.includes("kvalific") ||
    lowered.includes("uteslut")
  ) {
    return "qualification_appendix";
  }
  if (
    lowered.includes("requirement") ||
    lowered.includes("krav") ||
    lowered.includes("skakrav")
  ) {
    return "requirements_appendix";
  }
  if (
    lowered.includes("contract") ||
    lowered.includes("avtal") ||
    lowered.includes("villkor")
  ) {
    return "contract_terms";
  }
  return isFirstDocument ? "main_tender" : null;
}
