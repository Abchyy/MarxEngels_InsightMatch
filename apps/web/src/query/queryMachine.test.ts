import { describe, expect, it, vi } from "vitest";
import type {
  ModeSuggestionResponse,
  SearchMode,
  SearchRequest,
  SearchResponse,
} from "../contracts";
import { makeSearchResponse, SYNTHETIC_QUERY } from "../testing/fixtures";
import { QueryMachine, type QueryMachineDeps } from "./queryMachine";

const QUESTION = SYNTHETIC_QUERY;

function makeSuggestion(overrides: Partial<ModeSuggestionResponse> = {}): ModeSuggestionResponse {
  return {
    suggested_mode: "exact",
    confidence: 0.99,
    requires_user_selection: false,
    allowed_modes: ["exact", "claim", "timeline", "thematic"],
    reason_code: "KEYWORD",
    ...overrides,
  };
}

function questionSuggestion(): ModeSuggestionResponse {
  return makeSuggestion({
    suggested_mode: null,
    confidence: 0.91,
    requires_user_selection: true,
    allowed_modes: ["timeline", "thematic"],
    reason_code: "QUESTION_OR_DOMAIN",
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function buildRequest(query: string, mode: SearchMode): SearchRequest {
  return {
    query,
    mode,
    scope: { corpus_ids: ["syn_corpus_001"] },
    sort: null,
    cursor: null,
    page_size: 20,
    options: { include_generated_summaries: true, include_counter_evidence: true },
  };
}

function createHarness(
  options: {
    suggestMode?: QueryMachineDeps["suggestMode"];
    search?: QueryMachineDeps["search"];
  } = {},
) {
  const suggestMode = vi.fn(options.suggestMode ?? (() => Promise.resolve(makeSuggestion())));
  const search = vi.fn(options.search ?? (() => Promise.resolve(makeSearchResponse())));
  const machine = new QueryMachine({ suggestMode, search, buildRequest });
  return { machine, suggestMode, search };
}

function apiError(code: string, extra: { retryable?: boolean; details?: Record<string, unknown> } = {}) {
  return {
    payload: {
      request_id: "req_syn_err",
      error: { code, message: `合成错误：${code}`, retryable: extra.retryable ?? false, details: extra.details ?? {} },
    },
    status: 400,
  };
}

describe("QueryMachine 状态机骨架", () => {
  it("初始为 idle，输入查询文本不改变状态", () => {
    const { machine } = createHarness();
    expect(machine.getState().phase).toBe("idle");
    machine.setQuery(QUESTION);
    expect(machine.getState().phase).toBe("idle");
    expect(machine.getState().query).toBe(QUESTION);
  });

  it("空查询不发起任何网络请求", async () => {
    const { machine, suggestMode, search } = createHarness();
    machine.setQuery("   ");
    await machine.requestSuggestion();
    await machine.submit();
    expect(suggestMode).not.toHaveBeenCalled();
    expect(search).not.toHaveBeenCalled();
  });

  it("建议成功且无需用户选择时进入 ready 并采用建议模式", async () => {
    const { machine } = createHarness();
    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    const state = machine.getState();
    expect(state.phase).toBe("ready");
    expect(state.selectedMode).toBe("exact");
    expect(state.modeSource).toBe("suggested");
  });

  it("idle 直接提交时先走建议；无需选择则自动继续检索", async () => {
    const { machine, suggestMode, search } = createHarness();
    machine.setQuery(QUESTION);
    await machine.submit();
    expect(suggestMode).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledTimes(1);
    expect(machine.getState().phase).toBe("success");
  });

  it("置信度不足且无建议模式时，保持输入不变并交由用户四选一", async () => {
    const { machine, search } = createHarness({
      suggestMode: () =>
        Promise.resolve(
          makeSuggestion({ suggested_mode: null, requires_user_selection: false, confidence: 0.2 }),
        ),
    });
    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    const state = machine.getState();
    expect(state.phase).toBe("awaiting_mode_selection");
    if (state.phase !== "awaiting_mode_selection") return;
    expect(state.query).toBe(QUESTION);
    expect(state.allowedModes).toEqual(["exact", "claim", "timeline", "thematic"]);
    machine.selectMode("claim");
    await machine.submit();
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0]?.[0].mode).toBe("claim");
  });
});

describe("mode 所有权：用户选择不被静默覆盖", () => {
  it("回归：用户选择 claim 后修改 query，状态不再声称 claim，检索 mode 与可见 mode 一致", async () => {
    const { machine, search } = createHarness();
    machine.setQuery(QUESTION);
    machine.selectMode("claim");
    expect(machine.getState().phase).toBe("ready");
    expect(machine.getState().selectedMode).toBe("claim");

    machine.setQuery(`${QUESTION}（续）`);
    const afterEdit = machine.getState();
    expect(afterEdit.phase).toBe("idle");
    expect(afterEdit.selectedMode).toBeNull();
    expect(afterEdit.modeSource).toBeNull();

    await machine.requestSuggestion();
    const ready = machine.getState();
    expect(ready.phase).toBe("ready");
    expect(ready.selectedMode).toBe("exact");
    expect(ready.modeSource).toBe("suggested");

    await machine.submit();
    const request = search.mock.calls[0]?.[0];
    const finalState = machine.getState();
    expect(request?.mode).toBe("exact");
    expect(request?.mode).toBe(finalState.selectedMode);
  });

  it("同一查询重复建议时，用户明确选择优先于新建议", async () => {
    const { machine, search } = createHarness();
    machine.setQuery(QUESTION);
    machine.selectMode("claim");

    await machine.requestSuggestion();
    const state = machine.getState();
    expect(state.phase).toBe("ready");
    expect(state.selectedMode).toBe("claim");
    expect(state.modeSource).toBe("user");

    await machine.submit();
    expect(search.mock.calls[0]?.[0].mode).toBe("claim");
  });

  it("建议设置的 mode 可被后续建议更新", async () => {
    const suggestMode = vi
      .fn<QueryMachineDeps["suggestMode"]>()
      .mockResolvedValueOnce(makeSuggestion({ suggested_mode: "exact" }))
      .mockResolvedValue(makeSuggestion({ suggested_mode: "claim" }));
    const { machine } = createHarness({ suggestMode });

    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    expect(machine.getState().selectedMode).toBe("exact");
    expect(machine.getState().modeSource).toBe("suggested");

    await machine.requestSuggestion();
    expect(machine.getState().selectedMode).toBe("claim");
    expect(machine.getState().modeSource).toBe("suggested");
  });

  it("setQuery 取消在途检索的同时清空 mode", async () => {
    const pending = deferred<SearchResponse>();
    const { machine, search } = createHarness({ search: () => pending.promise });
    machine.setQuery(QUESTION);
    machine.selectMode("claim");
    const submitting = machine.submit();
    await flush();
    expect(machine.getState().phase).toBe("searching");

    machine.setQuery("另一个合成查询");
    const state = machine.getState();
    expect(state.phase).toBe("idle");
    expect(state.selectedMode).toBeNull();
    expect(state.modeSource).toBeNull();
    expect(search.mock.calls[0]?.[1]?.aborted).toBe(true);

    pending.resolve(makeSearchResponse());
    await submitting;
    expect(machine.getState().phase).toBe("idle");
  });
});

describe("问题/领域输入的模式选择门", () => {
  it("requires_user_selection=true：进入 awaiting，清除不适用旧选择，提交不发送 search", async () => {
    const { machine, search } = createHarness({
      suggestMode: () => Promise.resolve(questionSuggestion()),
    });
    machine.setQuery(QUESTION);
    machine.selectMode("exact");
    expect(machine.getState().phase).toBe("ready");

    await machine.requestSuggestion();
    const state = machine.getState();
    expect(state.phase).toBe("awaiting_mode_selection");
    expect(state.selectedMode).toBeNull();
    expect(state.modeSource).toBeNull();

    await machine.submit();
    expect(search).toHaveBeenCalledTimes(0);
    expect(machine.getState().phase).toBe("awaiting_mode_selection");
  });

  it("awaiting 中拒绝 allowed_modes 之外的选择", async () => {
    const { machine, search } = createHarness({
      suggestMode: () => Promise.resolve(questionSuggestion()),
    });
    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    machine.selectMode("exact");
    expect(machine.getState().phase).toBe("awaiting_mode_selection");
    await machine.submit();
    expect(search).not.toHaveBeenCalled();
  });

  it("用户明确选择 timeline 后才检索：mode 正确且 query 未改写", async () => {
    const { machine, search } = createHarness({
      suggestMode: () => Promise.resolve(questionSuggestion()),
    });
    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    machine.selectMode("timeline");
    expect(machine.getState().phase).toBe("ready");

    await machine.submit();
    expect(search).toHaveBeenCalledTimes(1);
    const request = search.mock.calls[0]?.[0];
    expect(request?.mode).toBe("timeline");
    expect(request?.query).toBe(QUESTION);
    expect(machine.getState().phase).toBe("success");
  });

  it("用户明确选择 thematic 后检索：mode 为 thematic", async () => {
    const { machine, search } = createHarness({
      suggestMode: () => Promise.resolve(questionSuggestion()),
    });
    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    machine.selectMode("thematic");
    await machine.submit();
    expect(search.mock.calls[0]?.[0].mode).toBe("thematic");
  });

  it("仍然适用的旧选择保留高亮，但仍需用户再确认一次才放行", async () => {
    const { machine, search } = createHarness({
      suggestMode: () => Promise.resolve(questionSuggestion()),
    });
    machine.setQuery(QUESTION);
    machine.selectMode("timeline");
    await machine.requestSuggestion();

    const state = machine.getState();
    expect(state.phase).toBe("awaiting_mode_selection");
    expect(state.selectedMode).toBe("timeline");
    expect(state.modeSource).toBe("user");
    await machine.submit();
    expect(search).not.toHaveBeenCalled();

    machine.selectMode("timeline");
    await machine.submit();
    expect(search).toHaveBeenCalledTimes(1);
  });
});

describe("取消与乱序响应", () => {
  it("新查询取消上一未完成检索，迟到的旧响应不得覆盖新状态", async () => {
    const first = deferred<SearchResponse>();
    const second = deferred<SearchResponse>();
    const search = vi.fn((request: SearchRequest, _signal: AbortSignal) =>
      request.query === "合成查询（旧）" ? first.promise : second.promise,
    );
    const { machine } = createHarness({ search });

    machine.setQuery("合成查询（旧）");
    await machine.requestSuggestion();
    const firstSubmit = machine.submit();
    await flush();
    expect(machine.getState().phase).toBe("searching");

    machine.setQuery("合成查询（新）");
    expect(machine.getState().phase).toBe("idle");
    expect(search.mock.calls[0]?.[1]?.aborted).toBe(true);

    await machine.requestSuggestion();
    const secondSubmit = machine.submit();
    await flush();
    expect(machine.getState().phase).toBe("searching");

    first.resolve(makeSearchResponse({ query: "合成查询（旧）" }));
    await flush();
    expect(machine.getState().phase).toBe("searching");

    second.resolve(makeSearchResponse({ query: "合成查询（新）" }));
    await flush();
    const state = machine.getState();
    expect(state.phase).toBe("success");
    if (state.phase === "success") {
      expect(state.response.query).toBe("合成查询（新）");
    }
    await firstSubmit;
    await secondSubmit;
  });

  it("建议请求同样可被新查询取消，迟到的建议被丢弃", async () => {
    const pending = deferred<ModeSuggestionResponse>();
    const suggestMode = vi.fn((_query: string, _signal: AbortSignal) => pending.promise);
    const { machine } = createHarness({ suggestMode });

    machine.setQuery(QUESTION);
    const request = machine.requestSuggestion();
    expect(machine.getState().phase).toBe("suggesting_mode");

    machine.setQuery("另一个合成问题");
    expect(machine.getState().phase).toBe("idle");
    expect(suggestMode.mock.calls[0]?.[1]?.aborted).toBe(true);

    pending.resolve(questionSuggestion());
    await request;
    expect(machine.getState().phase).toBe("idle");
  });

  it("回归：旧 query 的 idle submit 在 setQuery 后不得读取新 query 的 ready 并自动检索", async () => {
    const oldQuery = "【合成查询】旧";
    const newQuery = "【合成查询】新";
    const oldPending = deferred<ModeSuggestionResponse>();
    const suggestMode = vi.fn((query: string, _signal: AbortSignal) => {
      if (query === oldQuery) return oldPending.promise;
      return Promise.resolve(makeSuggestion({ suggested_mode: "claim" }));
    });
    const { machine, search } = createHarness({ suggestMode });

    machine.setQuery(oldQuery);
    const oldSubmit = machine.submit();
    await flush();
    expect(machine.getState().phase).toBe("suggesting_mode");

    machine.setQuery(newQuery);
    expect(machine.getState().phase).toBe("idle");
    expect(suggestMode.mock.calls[0]?.[1]?.aborted).toBe(true);

    await machine.requestSuggestion();
    expect(machine.getState().phase).toBe("ready");
    expect(machine.getState().query).toBe(newQuery);
    expect(machine.getState().selectedMode).toBe("claim");

    oldPending.resolve(makeSuggestion({ suggested_mode: "exact" }));
    await oldSubmit;
    await flush();

    expect(search).toHaveBeenCalledTimes(0);
    const final = machine.getState();
    expect(final.phase).toBe("ready");
    expect(final.query).toBe(newQuery);
    expect(final.selectedMode).toBe("claim");
  });

  it("回归：相同 query 字符串回退（old→new→old）仍使旧 submit 失效", async () => {
    const sharedQuery = QUESTION;
    const oldPending = deferred<ModeSuggestionResponse>();
    let suggestCalls = 0;
    const suggestMode = vi.fn((_query: string, _signal: AbortSignal) => {
      suggestCalls += 1;
      if (suggestCalls === 1) return oldPending.promise;
      return Promise.resolve(makeSuggestion({ suggested_mode: "thematic" }));
    });
    const { machine, search } = createHarness({ suggestMode });

    machine.setQuery(sharedQuery);
    const oldSubmit = machine.submit();
    await flush();

    machine.setQuery("【合成查询】中间态");
    machine.setQuery(sharedQuery);

    await machine.requestSuggestion();
    expect(machine.getState().phase).toBe("ready");
    expect(machine.getState().selectedMode).toBe("thematic");

    oldPending.resolve(makeSuggestion({ suggested_mode: "exact" }));
    await oldSubmit;
    await flush();

    expect(search).toHaveBeenCalledTimes(0);
    expect(machine.getState().phase).toBe("ready");
    expect(machine.getState().selectedMode).toBe("thematic");
  });
});

describe("响应与错误映射", () => {
  async function searchWith(response: Partial<SearchResponse>) {
    const harness = createHarness({ search: () => Promise.resolve(makeSearchResponse(response)) });
    harness.machine.setQuery(QUESTION);
    await harness.machine.requestSuggestion();
    await harness.machine.submit();
    return harness.machine.getState();
  }

  it("无警告且有结果 → success", async () => {
    expect((await searchWith({})).phase).toBe("success");
  });

  it("带服务器 warnings → partial", async () => {
    const state = await searchWith({
      warnings: [{ code: "RERANKER_UNAVAILABLE", message: "重排服务暂不可用", stage: "rerank" }],
    });
    expect(state.phase).toBe("partial");
  });

  it("带 insufficiency → partial", async () => {
    const state = await searchWith({
      insufficiency: { code: "INSUFFICIENT_SUPPORT", message: "支撑材料不足" },
    });
    expect(state.phase).toBe("partial");
  });

  it("零结果且无警告 → empty", async () => {
    const state = await searchWith({
      evidence: [],
      groups: [],
      overview: { evidence_count: 0, work_count: 0, volume_count: 0, result_note: "以下组织只基于列出的证据。" },
    });
    expect(state.phase).toBe("empty");
  });

  it("Exact NO_EXACT_MATCH 零结果 → empty（非 partial）", async () => {
    const state = await searchWith({
      mode: "exact",
      evidence: [],
      groups: [],
      insufficiency: { code: "NO_EXACT_MATCH", message: "【合成】无逐字命中" },
      overview: { evidence_count: 0, work_count: 0, volume_count: 0, result_note: "以下组织只基于列出的证据。" },
    });
    expect(state.phase).toBe("empty");
  });

  it("统一 ErrorResponse 进入 error 状态并保留 code/retryable", async () => {
    const { machine } = createHarness({
      search: () => Promise.reject(apiError("RATE_LIMITED", { retryable: true })),
    });
    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    await machine.submit();
    const state = machine.getState();
    expect(state.phase).toBe("error");
    if (state.phase !== "error") return;
    expect(state.error.code).toBe("RATE_LIMITED");
    expect(state.error.retryable).toBe(true);
    expect(state.selectedMode).toBe("exact");
    expect(state.modeSource).toBe("suggested");
  });

  it("MODE_SELECTION_REQUIRED 回到 awaiting_mode_selection 而非错误死胡同", async () => {
    const search = vi
      .fn<QueryMachineDeps["search"]>()
      .mockRejectedValueOnce(
        apiError("MODE_SELECTION_REQUIRED", { details: { allowed_modes: ["timeline", "thematic"] } }),
      )
      .mockResolvedValue(makeSearchResponse({ mode: "thematic" }));
    const { machine } = createHarness({ search });

    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    await machine.submit();

    const bounced = machine.getState();
    expect(bounced.phase).toBe("awaiting_mode_selection");
    if (bounced.phase !== "awaiting_mode_selection") return;
    expect(bounced.allowedModes).toEqual(["timeline", "thematic"]);
    expect(bounced.selectedMode).toBeNull();

    machine.selectMode("thematic");
    await machine.submit();
    expect(machine.getState().phase).toBe("success");
    expect(search).toHaveBeenCalledTimes(2);
  });

  it("建议请求失败进入 error，可重试恢复", async () => {
    const suggestMode = vi
      .fn<QueryMachineDeps["suggestMode"]>()
      .mockRejectedValueOnce(new Error("connection refused"))
      .mockResolvedValue(makeSuggestion());
    const { machine } = createHarness({ suggestMode });

    machine.setQuery(QUESTION);
    await machine.requestSuggestion();
    const failed = machine.getState();
    expect(failed.phase).toBe("error");
    if (failed.phase !== "error") return;
    expect(failed.error.code).toBe("NETWORK_ERROR");
    expect(failed.error.retryable).toBe(true);

    await machine.requestSuggestion();
    expect(machine.getState().phase).toBe("ready");
  });
});
