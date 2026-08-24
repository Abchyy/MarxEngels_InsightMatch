import type { FormEvent } from "react";
import { search, suggestMode } from "./api/client";
import { MODE_LABELS, ModeSelector } from "./components/ModeSelector";
import type { SearchMode, SearchRequest, SearchScope } from "./contracts";
import type { QueryMachineDeps } from "./query/queryMachine";
import { useQueryMachine } from "./query/useQueryMachine";
import "./styles.css";

const DEFAULT_SCOPE: SearchScope = {
  corpus_ids: ["marx_engels_collected_works_cn"],
  edition_ids: [],
  volume_ids: [],
  work_ids: [],
  authors: [],
  content_types: ["main_text", "author_note"],
};

const MACHINE_DEPS: QueryMachineDeps = {
  suggestMode: (query, signal) => suggestMode(query, signal),
  search: (request, signal) => search(request, signal),
  // query 逐字透传，不做任何改写；mode 只能来自用户的最终选择。
  buildRequest: (query, mode): SearchRequest => ({
    query,
    mode,
    scope: { ...DEFAULT_SCOPE },
    sort: null,
    cursor: null,
    page_size: 20,
    options: { include_generated_summaries: true, include_counter_evidence: true },
  }),
};

function isTimelineThematicChoice(allowedModes: readonly SearchMode[]): boolean {
  return (
    allowedModes.length === 2 &&
    allowedModes.includes("timeline") &&
    allowedModes.includes("thematic")
  );
}

export default function App() {
  const { state, machine } = useQueryMachine(MACHINE_DEPS);

  const busy = state.phase === "suggesting_mode" || state.phase === "searching";
  const awaiting = state.phase === "awaiting_mode_selection";
  const queryEmpty = !state.query.trim();
  const canSubmit =
    !busy &&
    !queryEmpty &&
    !awaiting &&
    !(state.phase === "error" && state.selectedMode === null);
  const result =
    state.phase === "success" || state.phase === "empty" || state.phase === "partial"
      ? state
      : null;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void machine.submit();
  }

  return (
    <main>
      <header>
        <p className="eyebrow">可核验的原典检索</p>
        <h1>马恩文本检索助手</h1>
        <p>当前范围：《马克思恩格斯文集》十卷</p>
      </header>

      <form onSubmit={handleSubmit}>
        <label htmlFor="query">输入词语、观点、问题或研究领域</label>
        <textarea
          id="query"
          value={state.query}
          onChange={(event) => machine.setQuery(event.target.value)}
          maxLength={500}
          rows={4}
          required
        />
        <div className="actions">
          <button
            type="button"
            onClick={() => void machine.requestSuggestion()}
            disabled={busy || queryEmpty}
          >
            {state.phase === "suggesting_mode" ? "建议中…" : "建议检索方式"}
          </button>
          <button type="submit" disabled={!canSubmit} aria-disabled={!canSubmit}>
            {state.phase === "searching" ? "检索中…" : "开始检索"}
          </button>
        </div>

        <ModeSelector
          value={state.selectedMode}
          onChange={(mode) => machine.selectMode(mode)}
          allowedModes={awaiting ? state.allowedModes : null}
          disabled={busy}
        />
        {awaiting && (
          <p className="hint" role="status">
            {isTimelineThematicChoice(state.allowedModes)
              ? "该输入是问题或研究领域，请明确选择“按时间呈现”或“按思想结构呈现”后再检索；在此之前不会发送检索请求。"
              : "识别置信度不足，请从以上检索方式中明确选择一种后再检索。"}
          </p>
        )}
      </form>

      <section className="status" aria-live="polite">
        <h2>状态</h2>
        {state.phase === "idle" && (
          <p>
            输入后可直接开始检索，系统会先给出检索方式建议；问题或研究领域需由你明确选择呈现方式。
          </p>
        )}
        {state.phase === "suggesting_mode" && <p>正在建议检索方式…</p>}
        {state.phase === "awaiting_mode_selection" && (
          <p>等待你选择检索方式（{state.allowedModes.map((mode) => MODE_LABELS[mode]).join(" / ")}）。</p>
        )}
        {state.phase === "ready" && (
          <p>
            已就绪：将以「{MODE_LABELS[state.selectedMode]}」检索，查询原文保持不变。
            {state.suggestion?.suggested_mode
              ? `（系统建议：${MODE_LABELS[state.suggestion.suggested_mode]}，置信度 ${state.suggestion.confidence}）`
              : ""}
          </p>
        )}
        {state.phase === "searching" && <p>正在检索，请稍候…新的查询会自动取消本次请求。</p>}
        {state.phase === "error" && (
          <div role="alert">
            <p>
              {state.error.code === "PIPELINE_NOT_IMPLEMENTED"
                ? "公共契约已经生效；该检索管线将在对应 Worktree 中实现。"
                : state.error.message}
            </p>
            <p className="error-meta">
              错误码：{state.error.code}
              {state.error.retryable ? "（可重试）" : ""}
              {state.error.requestId ? `，请求号：${state.error.requestId}` : ""}
            </p>
          </div>
        )}
        {result && (
          <div>
            <h3>
              {result.phase === "success" && "检索结果概览"}
              {result.phase === "empty" && "未找到结果"}
              {result.phase === "partial" && "部分结果（存在降级或提示）"}
            </h3>
            <dl className="overview">
              <dt>原查询</dt>
              <dd>{result.response.query}</dd>
              <dt>检索模式</dt>
              <dd>{MODE_LABELS[result.selectedMode]}</dd>
              <dt>实际范围</dt>
              <dd>
                语料 {result.response.scope_snapshot.corpus_ids.join("、") || "（空）"}；卷次{" "}
                {result.response.scope_snapshot.volume_ids?.length
                  ? result.response.scope_snapshot.volume_ids.join("、")
                  : "全部已发布卷"}
              </dd>
              <dt>证据 / 著作 / 卷次</dt>
              <dd>
                {result.response.overview.evidence_count} / {result.response.overview.work_count} /{" "}
                {result.response.overview.volume_count}
              </dd>
              <dt>数据版本</dt>
              <dd>
                {result.response.release.data_version}
                {result.response.release.index_version
                  ? `（索引 ${result.response.release.index_version}）`
                  : ""}
              </dd>
            </dl>
            {result.phase === "empty" && (
              <p>
                {result.selectedMode === "exact"
                  ? "在当前范围内未发现该词的逐字命中，可改用语义检索重试。"
                  : "在当前范围内未发现相关证据，可扩大范围或修改查询后重试。"}
              </p>
            )}
            {result.phase === "partial" && (
              <div className="warnings">
                {result.response.insufficiency && (
                  <p>证据不足：{result.response.insufficiency.message}</p>
                )}
                {(result.response.warnings ?? []).map((warning) => (
                  <p key={`${warning.stage}:${warning.code}`}>
                    警告[{warning.stage}/{warning.code}]：{warning.message}
                  </p>
                ))}
              </div>
            )}
            <p className="notice">{result.response.overview.result_note}</p>
            <p className="notice">
              四种结果视图（精确列表 / 观点分组 / 时间轴 / 主题组）将在后续批次实现，本批次仅展示概览。
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
