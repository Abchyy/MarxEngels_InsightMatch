import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { search, suggestMode } from "./api/client";
import { MODE_LABELS, ModeSelector } from "./components/ModeSelector";
import type { SearchMode, SearchRequest } from "./contracts";
import {
  SYNTHETIC_DEMO_BANNER,
  SYNTHETIC_DEMO_EXAMPLES,
  buildSearchRequest,
  isSyntheticDemoMode,
  type SyntheticDemoExample,
} from "./demo/syntheticDemo";
import type { QueryMachineDeps } from "./query/queryMachine";
import { useQueryMachine } from "./query/useQueryMachine";
import { ResultPage } from "./views/ResultPage";
import type { ExactSort } from "./views/ExactResultList";
import "./styles.css";

function isTimelineThematicChoice(allowedModes: readonly SearchMode[]): boolean {
  return (
    allowedModes.length === 2 &&
    allowedModes.includes("timeline") &&
    allowedModes.includes("thematic")
  );
}

export function SearchApp({ demoMode }: { demoMode: boolean }) {
  const [exactSort, setExactSort] = useState<ExactSort | null>(null);

  const machineDeps = useMemo<QueryMachineDeps>(
    () => ({
      suggestMode: (query, signal) => suggestMode(query, signal),
      search: (request, signal) => search(request, signal),
      buildRequest: (query, mode): SearchRequest =>
        buildSearchRequest(query, mode, exactSort, demoMode),
    }),
    [exactSort, demoMode],
  );

  const { state, machine } = useQueryMachine(machineDeps);

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

  function handleSuggestModeSwitch(mode: SearchMode) {
    machine.selectMode(mode);
  }

  function applyDemoExample(example: SyntheticDemoExample) {
    machine.setQuery(example.query);
    machine.selectMode(example.mode);
  }

  return (
    <main>
      <header>
        {demoMode && (
          <p className="demo-banner" role="status">
            {SYNTHETIC_DEMO_BANNER}
          </p>
        )}
        <p className="eyebrow">可核验的原典检索</p>
        <h1>马恩文本检索助手</h1>
        <p>
          {demoMode
            ? "当前范围：合成测试语料（禁止作为引文）"
            : "当前范围：《马克思恩格斯文集》十卷"}
        </p>
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
        {demoMode && (
          <div className="demo-examples">
            <p className="demo-examples__label">合成演示查询（点击填入，不改写检索状态机）</p>
            <ul>
              {SYNTHETIC_DEMO_EXAMPLES.map((example) => (
                <li key={example.mode}>
                  <button
                    type="button"
                    className="demo-example"
                    onClick={() => applyDemoExample(example)}
                    disabled={busy}
                  >
                    <span className="demo-example__mode">{example.label}</span>
                    <span className="demo-example__query">{example.query}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
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
          <ResultPage
            response={result.response}
            selectedMode={result.selectedMode}
            phase={result.phase}
            matchQuery={result.response.query.trim()}
            exactSort={exactSort}
            onExactSortChange={setExactSort}
            onSuggestModeSwitch={handleSuggestModeSwitch}
          />
        )}
      </section>
    </main>
  );
}

export default function App() {
  return <SearchApp demoMode={isSyntheticDemoMode()} />;
}
