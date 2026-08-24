import type { Evidence } from "../contracts";

export function buildEvidenceMap(evidence: Evidence[] | undefined): Map<string, Evidence> {
  const map = new Map<string, Evidence>();
  for (const item of evidence ?? []) {
    map.set(item.evidence_id, item);
  }
  return map;
}

export function resolveEvidence(
  ids: string[] | undefined,
  map: Map<string, Evidence>,
): Evidence[] {
  return (ids ?? [])
    .map((id) => map.get(id))
    .filter((item): item is Evidence => item !== undefined);
}
