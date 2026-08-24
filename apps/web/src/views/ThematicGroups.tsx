import { useMemo, useState } from "react";
import type { Evidence, ResultGroup } from "../contracts";
import { EvidenceCard } from "../components/EvidenceCard";
import { THEMATIC_CLASSIFICATION_NOTICE } from "../components/labels";
import { buildEvidenceMap, resolveEvidence } from "./evidenceMap";

/** 同一 evidence 只出现在第一个遇到的组中；other_related 始终保留可见。 */
export function dedupeThematicGroups(groups: ResultGroup[]): ResultGroup[] {
  const seen = new Set<string>();
  return groups.map((group) => {
    const ids = (group.evidence_ids ?? []).filter((id) => {
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
    return { ...group, evidence_ids: ids };
  });
}

export function resolveThematicLabel(
  group: ResultGroup,
  themeIndex: number,
  showMachineLabels: boolean,
): string {
  if (group.group_type === "other_related") {
    return group.label || "其他相关材料";
  }
  if (showMachineLabels && group.label) {
    return group.label;
  }
  return `主题 ${themeIndex}`;
}

interface Props {
  groups: ResultGroup[] | undefined;
  evidence: Evidence[] | undefined;
  classificationNotice?: string | null;
  showMachineLabels?: boolean;
  onShowMachineLabelsChange?: (show: boolean) => void;
}

export function ThematicGroups({
  groups,
  evidence,
  classificationNotice,
  showMachineLabels: controlledLabels,
  onShowMachineLabelsChange,
}: Props) {
  const [internalLabels, setInternalLabels] = useState(true);
  const showMachineLabels = controlledLabels ?? internalLabels;
  const setShowMachineLabels = onShowMachineLabelsChange ?? setInternalLabels;

  const evidenceMap = useMemo(() => buildEvidenceMap(evidence), [evidence]);
  const deduped = useMemo(() => dedupeThematicGroups(groups ?? []), [groups]);

  let themeIndex = 0;

  return (
    <section className="result-view result-view--thematic" aria-label="思想结构结果">
      <p className="thematic-notice" role="note">
        {classificationNotice ?? THEMATIC_CLASSIFICATION_NOTICE}
      </p>

      <div className="view-controls">
        <label>
          <input
            type="checkbox"
            checked={showMachineLabels}
            onChange={(event) => setShowMachineLabels(event.target.checked)}
          />
          显示机器主题标签
        </label>
      </div>

      {deduped.length === 0 ? (
        <p role="status">未找到可归类的主题组。</p>
      ) : (
        <ol className="thematic-groups">
          {deduped.map((group) => {
            const isOther = group.group_type === "other_related";
            const label = resolveThematicLabel(
              group,
              isOther ? 0 : ++themeIndex,
              showMachineLabels,
            );
            const items = resolveEvidence(group.evidence_ids, evidenceMap);
            const count = items.length;

            return (
              <li
                key={group.group_id}
                className={`thematic-group${isOther ? " thematic-group--other" : ""}`}
              >
                <header className="thematic-group__header">
                  <h4>{label}</h4>
                  <p className="thematic-group__count">{count} 条证据</p>
                  {showMachineLabels && group.summary && (
                    <p className="thematic-group__summary machine-summary">
                      <span className="machine-summary__badge">机器归纳</span>
                      {group.summary}
                    </p>
                  )}
                </header>
                {count > 0 ? (
                  <ol className="evidence-list">
                    {items.map((item) => (
                      <li key={item.evidence_id}>
                        <EvidenceCard evidence={item} />
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="thematic-group__empty">本组暂无可展示证据。</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
