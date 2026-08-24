import type { Evidence } from "../contracts";
import { HighlightedText } from "./HighlightedText";
import { MATCH_TYPE_LABELS, SUPPORT_LABELS } from "./labels";

interface Props {
  evidence: Evidence;
  /** exact 模式：起始码点位置 + 匹配 query（仅 trim 用于长度） */
  highlightOffsets?: number[];
  matchQuery?: string;
}

function formatPages(pages: string[] | undefined): string {
  return pages?.length ? pages.join("、") : "—";
}

function formatPdfPages(pages: number[] | undefined): string {
  return pages?.length ? pages.map(String).join("、") : "—";
}

export function EvidenceCard({ evidence, highlightOffsets, matchQuery }: Props) {
  const supportLabel = evidence.support_label;
  const matchLabel = MATCH_TYPE_LABELS[evidence.match_type] ?? evidence.match_type;
  const useHighlight = highlightOffsets != null && matchQuery != null && matchQuery.trim().length > 0;

  return (
    <article className="evidence-card" aria-labelledby={`evidence-${evidence.evidence_id}-heading`}>
      <header className="evidence-card__header">
        <div className="evidence-card__tags" aria-label="命中与支撑标签">
          <span className="tag tag-match">{matchLabel}</span>
          {supportLabel && (
            <span
              className={`tag tag-support tag-support--${supportLabel}`}
              aria-label={`支撑关系：${SUPPORT_LABELS[supportLabel]}`}
            >
              {SUPPORT_LABELS[supportLabel]}
            </span>
          )}
          {evidence.exact_match_count != null && evidence.exact_match_count > 0 && (
            <span className="tag tag-count">命中 {evidence.exact_match_count} 次</span>
          )}
        </div>
        {(evidence.rank_reasons?.length ?? 0) > 0 && (
          <ul className="rank-reasons" aria-label="排序理由">
            {evidence.rank_reasons!.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </header>

      <blockquote className="evidence-card__quote" cite={`#evidence-${evidence.evidence_id}`}>
        <p id={`evidence-${evidence.evidence_id}-heading`}>
          {useHighlight ? (
            <HighlightedText
              text={evidence.verified_text}
              offsets={highlightOffsets}
              matchQuery={matchQuery}
            />
          ) : (
            evidence.verified_text
          )}
        </p>
      </blockquote>

      <footer className="evidence-card__meta">
        <dl>
          <div>
            <dt>作者</dt>
            <dd>{evidence.author}</dd>
          </div>
          <div>
            <dt>著作</dt>
            <dd>{evidence.work_title}</dd>
          </div>
          <div>
            <dt>版本</dt>
            <dd>{evidence.edition_label}</dd>
          </div>
          <div>
            <dt>卷次</dt>
            <dd>第 {evidence.volume_no} 卷</dd>
          </div>
          <div>
            <dt>印刷页</dt>
            <dd>{formatPages(evidence.printed_pages)}</dd>
          </div>
          <div>
            <dt>PDF 页</dt>
            <dd>{formatPdfPages(evidence.pdf_pages)}</dd>
          </div>
        </dl>
      </footer>
    </article>
  );
}
