import type { Evidence, ResultGroup } from "../contracts";
import { EvidenceCard } from "../components/EvidenceCard";
import { buildEvidenceMap, resolveEvidence } from "./evidenceMap";

type ClaimBucket = "direct" | "indirect" | "counter";

const BUCKET_META: Record<ClaimBucket, { title: string; groupTypes: string[] }> = {
  direct: { title: "直接支撑", groupTypes: ["supporting", "direct"] },
  indirect: { title: "间接相关", groupTypes: ["contextual", "indirect"] },
  counter: { title: "相反材料", groupTypes: ["counter"] },
};

const BUCKET_ORDER: ClaimBucket[] = ["direct", "indirect", "counter"];

function bucketForEvidence(item: Evidence): ClaimBucket {
  switch (item.support_label) {
    case "direct":
      return "direct";
    case "counter":
      return "counter";
    default:
      return "indirect";
  }
}

function groupEvidence(
  groups: ResultGroup[] | undefined,
  evidence: Evidence[] | undefined,
): Record<ClaimBucket, Evidence[]> {
  const map = buildEvidenceMap(evidence);
  const buckets: Record<ClaimBucket, Evidence[]> = { direct: [], indirect: [], counter: [] };
  const assigned = new Set<string>();

  for (const bucket of BUCKET_ORDER) {
    const meta = BUCKET_META[bucket];
    for (const group of groups ?? []) {
      if (!meta.groupTypes.includes(group.group_type)) continue;
      for (const item of resolveEvidence(group.evidence_ids, map)) {
        if (assigned.has(item.evidence_id)) continue;
        buckets[bucket].push(item);
        assigned.add(item.evidence_id);
      }
    }
  }

  for (const item of evidence ?? []) {
    if (assigned.has(item.evidence_id)) continue;
    buckets[bucketForEvidence(item)].push(item);
    assigned.add(item.evidence_id);
  }

  return buckets;
}

interface Props {
  response: Pick<import("../contracts").SearchResponse, "groups" | "evidence">;
}

/** 证据不足由 SearchOverview 首屏统一展示，此处不再重复。 */
export function ClaimResultGroups({ response }: Props) {
  const buckets = groupEvidence(response.groups, response.evidence);

  return (
    <section className="result-view result-view--claim" aria-label="观点语义检索结果">
      {BUCKET_ORDER.map((bucket) => {
        const items = buckets[bucket];
        const openByDefault = bucket === "direct";
        return (
          <details key={bucket} className="claim-group" open={openByDefault}>
            <summary>
              {BUCKET_META[bucket].title}
              <span className="claim-group__count">（{items.length} 条）</span>
            </summary>
            {items.length === 0 ? (
              <p className="claim-group__empty">暂无{BUCKET_META[bucket].title}。</p>
            ) : (
              <ol className="evidence-list">
                {items.map((item) => (
                  <li key={item.evidence_id}>
                    <EvidenceCard evidence={item} />
                  </li>
                ))}
              </ol>
            )}
          </details>
        );
      })}
    </section>
  );
}
