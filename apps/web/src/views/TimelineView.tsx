import { useMemo, useState } from "react";
import type { DatePrecision, Evidence, ResultGroup } from "../contracts";
import { EvidenceCard } from "../components/EvidenceCard";
import { formatDateRange } from "../components/labels";
import { buildEvidenceMap, resolveEvidence } from "./evidenceMap";

const UNKNOWN_LAST: DatePrecision[] = ["unknown", "disputed"];

function sortTimelineGroups(groups: ResultGroup[]): ResultGroup[] {
  return [...groups].sort((a, b) => {
    const aUnknown = UNKNOWN_LAST.includes(a.date_precision ?? "unknown");
    const bUnknown = UNKNOWN_LAST.includes(b.date_precision ?? "unknown");
    if (aUnknown !== bUnknown) return aUnknown ? 1 : -1;
    const aStart = a.date_start ?? "";
    const bStart = b.date_start ?? "";
    return aStart.localeCompare(bStart);
  });
}

function groupByWork(items: Evidence[]): Map<string, Evidence[]> {
  const map = new Map<string, Evidence[]>();
  for (const item of items) {
    const key = item.work_title;
    const list = map.get(key) ?? [];
    list.push(item);
    map.set(key, list);
  }
  return map;
}

interface Props {
  groups: ResultGroup[] | undefined;
  evidence: Evidence[] | undefined;
  /** 测试用：受控摘要可见性 */
  showSummaries?: boolean;
  onShowSummariesChange?: (show: boolean) => void;
}

export function TimelineView({
  groups,
  evidence,
  showSummaries: controlledShow,
  onShowSummariesChange,
}: Props) {
  const [internalShow, setInternalShow] = useState(true);
  const showSummaries = controlledShow ?? internalShow;
  const setShowSummaries = onShowSummariesChange ?? setInternalShow;

  const evidenceMap = useMemo(() => buildEvidenceMap(evidence), [evidence]);
  const sortedGroups = useMemo(() => sortTimelineGroups(groups ?? []), [groups]);

  if (sortedGroups.length === 0 && (evidence?.length ?? 0) === 0) {
    return (
      <section className="result-view result-view--timeline result-view--empty">
        <p role="status">未找到可排列的时间序列证据。</p>
      </section>
    );
  }

  const timelineGroups =
    sortedGroups.length > 0
      ? sortedGroups
      : [
          {
            group_id: "fallback",
            group_type: "period",
            label: "全部证据",
            date_start: null,
            date_end: null,
            date_precision: "unknown" as const,
            evidence_ids: evidence?.map((e) => e.evidence_id),
          },
        ];

  return (
    <section className="result-view result-view--timeline" aria-label="时间序列结果">
      <div className="view-controls">
        <label>
          <input
            type="checkbox"
            checked={showSummaries}
            onChange={(event) => setShowSummaries(event.target.checked)}
          />
          显示机器阶段摘要
        </label>
      </div>

      <ol className="timeline">
        {timelineGroups.map((group) => {
          const items = resolveEvidence(group.evidence_ids, evidenceMap);
          const dateLabel = formatDateRange(group.date_start, group.date_end, group.date_precision);
          const byWork = groupByWork(items);

          return (
            <li key={group.group_id} className="timeline__entry">
              <header className="timeline__header">
                <h4>{group.label}</h4>
                <p className="timeline__date" aria-label={`时间标识：${dateLabel}`}>
                  {dateLabel}
                </p>
                {showSummaries && group.summary && (
                  <p className="timeline__summary machine-summary">
                    <span className="machine-summary__badge">机器归纳</span>
                    {group.summary}
                  </p>
                )}
              </header>

              {[...byWork.entries()].map(([workTitle, workItems]) =>
                workItems.length > 1 ? (
                  <details key={workTitle} className="timeline__work-collapse" open>
                    <summary>
                      {workTitle}
                      <span className="timeline__work-count">（{workItems.length} 段）</span>
                    </summary>
                    <ol className="evidence-list">
                      {workItems.map((item) => (
                        <li key={item.evidence_id}>
                          <EvidenceCard evidence={item} />
                        </li>
                      ))}
                    </ol>
                  </details>
                ) : (
                  <ol key={workTitle} className="evidence-list">
                    {workItems.map((item) => (
                      <li key={item.evidence_id}>
                        <EvidenceCard evidence={item} />
                      </li>
                    ))}
                  </ol>
                ),
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
