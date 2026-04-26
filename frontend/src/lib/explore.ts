import type { ExternalTender } from "@/data/exploreMock";

const SAVED_KEY = "bidded.saved_tenders";
const IMPORTED_KEY = "bidded.imported_procurements";

export function getSavedTenderIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(SAVED_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

export function isTenderSaved(id: string): boolean {
  return getSavedTenderIds().includes(id);
}

export function toggleSavedTender(id: string): boolean {
  const current = getSavedTenderIds();
  const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
  window.localStorage.setItem(SAVED_KEY, JSON.stringify(next));
  return next.includes(id);
}

interface ImportedRecord {
  id: string;
  companyId: string;
  title: string;
  importedAt: string;
}

function getImportedRecords(): ImportedRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(IMPORTED_KEY);
    return raw ? (JSON.parse(raw) as ImportedRecord[]) : [];
  } catch {
    return [];
  }
}

function saveImportedRecords(items: ImportedRecord[]) {
  window.localStorage.setItem(IMPORTED_KEY, JSON.stringify(items));
}

export function isTenderImported(externalId: string, companyId: string | null | undefined): boolean {
  return getImportedRecords().some(
    (r) => r.id === `imp-${externalId}` && (companyId ? r.companyId === companyId : true),
  );
}

export function importExternalTender(ext: ExternalTender, companyId: string): void {
  const record: ImportedRecord = {
    id: `imp-${ext.id}`,
    companyId,
    title: ext.title,
    importedAt: new Date().toISOString(),
  };
  const current = getImportedRecords();
  const next = [record, ...current.filter((r) => r.id !== record.id)];
  saveImportedRecords(next);
}
