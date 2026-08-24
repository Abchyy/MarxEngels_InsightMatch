import type { Evidence, Insufficiency, SearchMode } from "../contracts";
import { EvidenceCard } from "../components/EvidenceCard";

export type ExactSort = "relevance" | "document_order";

interface Props {
  evidence: Evidence[];
  /** 仅 trim 首尾空白，用于高亮长度计算；显示 query 仍以 response.query 为准 */
  matchQuery: string;
  sort: ExactSort | null;
  onSortChange: (sort: ExactSort) => void;
  onSuggestModeSwitch?: (mode: SearchMode) => void;
  insufficiency?: Insufficiency | null;
}

export function ExactResultList({
  evidence,
  matchQuery,
  sort,
  onSortChange,
  onSuggestModeSwitch,
  insufficiency,
}: Props) {
  if (evidence.length === 0) {
    return (
      <div className="result-view result-view--exact result-view--empty">
        <p role="status">
          {insufficiency?.code === "NO_EXACT_MATCH" && insufficiency.message
            ? insufficiency.message
            : "在当前范围内未发现该词的逐字命中。"}
        </p>
        {onSuggestModeSwitch && (
          <button type="button" className="suggest-switch" onClick={() => onSuggestModeSwitch("claim")}>
            改用语义检索（需手动提交，不会自动发起请求）
          </button>
        )}
      </div>
    );
  }

  return (
    <section className="result-view result-view--exact" aria-label="精确检索结果">
      <fieldset className="view-controls">
        <legend>结果排序</legend>
        <label>
          <input
            type="radio"
            name="exact-sort"
            value="relevance"
            checked={sort === "relevance" || sort === null}
            onChange={() => onSortChange("relevance")}
          />
          按相关度
        </label>
        <label>
          <input
            type="radio"
            name="exact-sort"
            value="document_order"
            checked={sort === "document_order"}
            onChange={() => onSortChange("document_order")}
          />
          按卷页顺序
        </label>
        <p className="view-controls__hint">排序将在下次点击「开始检索」时生效，不会自动重新查询。</p>
      </fieldset>

      <ol className="evidence-list">
        {evidence.map((item) => (
          <li key={item.evidence_id}>
            <EvidenceCard
              evidence={item}
              highlightOffsets={item.match_offsets}
              matchQuery={matchQuery}
            />
          </li>
        ))}
      </ol>
    </section>
  );
}
