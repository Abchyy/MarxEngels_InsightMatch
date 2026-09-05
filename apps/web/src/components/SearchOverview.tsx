import { MODE_LABELS } from "./ModeSelector";
import type { Insufficiency, SearchMode, SearchResponse, Warning } from "../contracts";

interface Props {
  response: SearchResponse;
  selectedMode: SearchMode;
  phase: "success" | "empty" | "partial";
}

function WarningsBlock({ warnings }: { warnings: Warning[] }) {
  return (
    <div className="warnings" role="status">
      {warnings.map((warning) => (
        <p key={`${warning.stage}:${warning.code}`}>
          警告[{warning.stage}/{warning.code}]：{warning.message}
        </p>
      ))}
    </div>
  );
}

function InsufficiencyBlock({ insufficiency }: { insufficiency: Insufficiency }) {
  return (
    <div className="insufficiency insufficiency--overview" role="status">
      <p>
        <strong>证据不足：</strong>
        {insufficiency.message}
      </p>
    </div>
  );
}

/** insufficiency 在结果页首屏只展示一次（Claim 等）；Exact NO_EXACT_MATCH 由视图区展示。 */
export function shouldShowOverviewInsufficiency(
  response: SearchResponse,
  phase: "success" | "empty" | "partial",
): boolean {
  const insufficiency = response.insufficiency;
  if (!insufficiency) return false;
  if (insufficiency.code === "NO_EXACT_MATCH" && response.mode === "exact") return false;
  return phase === "partial" || response.mode === "claim";
}

export function SearchOverview({ response, selectedMode, phase }: Props) {
  const warnings = response.warnings ?? [];
  const showInsufficiency = shouldShowOverviewInsufficiency(response, phase);

  return (
    <div className="search-overview">
      <h3>
        {phase === "success" && "检索结果概览"}
        {phase === "empty" && "未找到结果"}
        {phase === "partial" && "部分结果（存在降级或提示）"}
      </h3>

      {showInsufficiency && response.insufficiency && (
        <InsufficiencyBlock insufficiency={response.insufficiency} />
      )}

      {warnings.length > 0 && <WarningsBlock warnings={warnings} />}

      <dl className="overview">
        <dt>原查询</dt>
        <dd>{response.query}</dd>
        <dt>检索模式</dt>
        <dd>{MODE_LABELS[selectedMode]}</dd>
        <dt>实际范围</dt>
        <dd>
          语料 {response.scope_snapshot.corpus_ids.join("、") || "（空）"}；卷次{" "}
          {response.scope_snapshot.volume_ids?.length
            ? response.scope_snapshot.volume_ids.join("、")
            : "全部已发布卷"}
        </dd>
        <dt>证据 / 著作 / 卷次</dt>
        <dd>
          {response.overview.evidence_count} / {response.overview.work_count} /{" "}
          {response.overview.volume_count}
        </dd>
        <dt>数据版本</dt>
        <dd className="data-version">
          {response.release.data_version}
          {response.release.index_version ? `（索引 ${response.release.index_version}）` : ""}
        </dd>
      </dl>

      <p className="notice">{response.overview.result_note}</p>
    </div>
  );
}
