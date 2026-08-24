import { FormEvent, useState } from "react";
import { ApiClientError, search, suggestMode } from "./api/client";
import { ModeSelector } from "./components/ModeSelector";
import type { SearchMode, SearchRequest } from "./contracts";
import "./styles.css";

const DEFAULT_CORPUS = "marx_engels_collected_works_cn";

export default function App() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("exact");
  const [status, setStatus] = useState("主体架构已就绪；检索管线等待并行开发。\n");
  const [busy, setBusy] = useState(false);

  async function handleSuggest() {
    if (!query.trim()) return;
    setBusy(true);
    try {
      const suggestion = await suggestMode(query);
      if (suggestion.requires_user_selection) {
        setStatus("该输入需要选择“按时间呈现”或“按思想结构呈现”。");
      } else if (suggestion.suggested_mode) {
        setMode(suggestion.suggested_mode);
        setStatus(`已建议 ${suggestion.suggested_mode} 模式。`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "模式建议失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: SearchRequest = {
      query,
      mode,
      scope: {
        corpus_ids: [DEFAULT_CORPUS],
        edition_ids: [],
        volume_ids: [],
        work_ids: [],
        authors: [],
        content_types: ["main_text", "author_note"],
      },
      sort: null,
      cursor: null,
      page_size: 20,
      options: { include_generated_summaries: true, include_counter_evidence: true },
    };
    setBusy(true);
    try {
      await search(payload);
      setStatus("检索完成。");
    } catch (error) {
      if (error instanceof ApiClientError && error.payload.error.code === "PIPELINE_NOT_IMPLEMENTED") {
        setStatus("公共契约已经生效；该检索管线将在对应 Worktree 中实现。");
      } else {
        setStatus(error instanceof Error ? error.message : "检索失败");
      }
    } finally {
      setBusy(false);
    }
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
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          maxLength={500}
          rows={4}
          required
        />
        <div className="actions">
          <button type="button" onClick={handleSuggest} disabled={busy || !query.trim()}>
            建议检索方式
          </button>
          <button type="submit" disabled={busy || !query.trim()}>
            {busy ? "处理中…" : "开始检索"}
          </button>
        </div>
        <ModeSelector value={mode} onChange={setMode} />
      </form>

      <section className="status" aria-live="polite">
        <h2>开发基准状态</h2>
        <p>{status}</p>
        <p className="notice">以下组织只基于列出的证据；正式引文只能由 SQLite 回填。</p>
      </section>
    </main>
  );
}
