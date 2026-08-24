import type {
  ApiError,
  ModeSuggestionResponse,
  SearchMode,
  SearchRequest,
  SearchResponse,
} from "../contracts";

/**
 * 查询输入状态机，契约来源：04 规范 §12.2。
 *
 * idle → suggesting_mode → awaiting_mode_selection | ready
 *     → searching → success | empty | partial | error
 *
 * 关键不变量：
 * - awaiting_mode_selection 下绝不发送 search 请求；只有用户明确选择
 *   allowed_modes 中的模式（问题/领域输入即 timeline/thematic）才进入 ready。
 * - 查询原文透传，任何阶段不改写。
 * - 新查询（setQuery / 再次提交）取消上一未完成请求；乱序响应由序号防护，
 *   旧响应不得覆盖新状态；idle submit 仅在其 requestSuggestion 仍有效时才
 *   自动检索，避免跨查询异步竞态。
 * - mode 所有权：查询文本一变即清空 selectedMode，不留任何可能被后续建议
 *   静默覆盖的可见选择；同一查询下 user 确认的选择优先于 suggested_mode，
 *   建议只能填空位或更新由建议自己设置的值。
 */
export type ModeSource = "user" | "suggested";

export type QueryState =
  | { phase: "idle"; query: string; selectedMode: null; modeSource: null }
  | {
      phase: "suggesting_mode";
      query: string;
      selectedMode: SearchMode | null;
      modeSource: ModeSource | null;
    }
  | {
      phase: "awaiting_mode_selection";
      query: string;
      selectedMode: SearchMode | null;
      modeSource: ModeSource | null;
      allowedModes: SearchMode[];
      suggestion: ModeSuggestionResponse | null;
    }
  | {
      phase: "ready";
      query: string;
      selectedMode: SearchMode;
      modeSource: ModeSource;
      suggestion: ModeSuggestionResponse | null;
    }
  | { phase: "searching"; query: string; selectedMode: SearchMode; modeSource: ModeSource }
  | {
      phase: "success";
      query: string;
      selectedMode: SearchMode;
      modeSource: ModeSource;
      response: SearchResponse;
    }
  | {
      phase: "empty";
      query: string;
      selectedMode: SearchMode;
      modeSource: ModeSource;
      response: SearchResponse;
    }
  | {
      phase: "partial";
      query: string;
      selectedMode: SearchMode;
      modeSource: ModeSource;
      response: SearchResponse;
    }
  | {
      phase: "error";
      query: string;
      selectedMode: SearchMode | null;
      modeSource: ModeSource | null;
      error: QueryError;
    };

export type QueryPhase = QueryState["phase"];

export interface QueryError {
  code: string;
  message: string;
  retryable: boolean;
  status?: number;
  requestId?: string;
  details?: Record<string, unknown>;
}

export interface QueryMachineDeps {
  suggestMode: (query: string, signal: AbortSignal) => Promise<ModeSuggestionResponse>;
  search: (request: SearchRequest, signal: AbortSignal) => Promise<SearchResponse>;
  buildRequest: (query: string, mode: SearchMode) => SearchRequest;
}

export const ALL_MODES: readonly SearchMode[] = ["exact", "claim", "timeline", "thematic"];

/** 服务器警告或证据不足提示意味着结果不完整，对应 04 规范 §14 的 Partial 行。 */
export function classifySearchResponse(response: SearchResponse): "success" | "empty" | "partial" {
  if ((response.warnings?.length ?? 0) > 0 || response.insufficiency != null) return "partial";
  const evidenceCount = response.evidence?.length ?? response.overview.evidence_count;
  const groupCount = response.groups?.length ?? 0;
  return evidenceCount === 0 && groupCount === 0 ? "empty" : "success";
}

function isAbortError(error: unknown): boolean {
  return (error as { name?: unknown })?.name === "AbortError";
}

function extractApiError(error: unknown): { payload: ApiError; status?: number } | null {
  if (typeof error !== "object" || error === null) return null;
  const payload = (error as { payload?: unknown }).payload;
  if (typeof payload !== "object" || payload === null) return null;
  const body = (payload as ApiError).error;
  if (typeof body?.code !== "string" || typeof body?.message !== "string") return null;
  const status = (error as { status?: unknown }).status;
  return { payload: payload as ApiError, status: typeof status === "number" ? status : undefined };
}

function toQueryError(error: unknown): QueryError {
  const api = extractApiError(error);
  if (api) {
    return {
      code: api.payload.error.code,
      message: api.payload.error.message,
      retryable: api.payload.error.retryable ?? false,
      details: api.payload.error.details,
      requestId: api.payload.request_id,
      status: api.status,
    };
  }
  if (error instanceof Error) {
    return { code: "NETWORK_ERROR", message: error.message, retryable: true };
  }
  return { code: "UNKNOWN_ERROR", message: String(error), retryable: false };
}

function sanitizeAllowedModes(modes: unknown): SearchMode[] {
  if (!Array.isArray(modes)) return [];
  return modes.filter((mode): mode is SearchMode =>
    typeof mode === "string" && (ALL_MODES as readonly string[]).includes(mode),
  );
}

export class QueryMachine {
  private state: QueryState = { phase: "idle", query: "", selectedMode: null, modeSource: null };
  private readonly listeners = new Set<(state: QueryState) => void>();
  private inFlight: AbortController | null = null;
  private sequence = 0;

  constructor(private readonly deps: QueryMachineDeps) {}

  getState(): QueryState {
    return this.state;
  }

  subscribe(listener: (state: QueryState) => void): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => {
      this.listeners.delete(listener);
    };
  }

  dispose(): void {
    this.cancelInFlight();
    this.listeners.clear();
  }

  /**
   * 查询文本变化即构成新查询：取消在途请求、旧建议/结果失效，并清空
   * selectedMode —— 不让一个可见的旧 mode 留下来被下一次建议静默覆盖。
   */
  setQuery(query: string): void {
    if (query === this.state.query) return;
    this.cancelInFlight();
    this.set({ phase: "idle", query, selectedMode: null, modeSource: null });
  }

  /** 用户明确选择检索方式（modeSource=user）；awaiting 中只允许 allowed_modes 内的模式。 */
  selectMode(mode: SearchMode): void {
    const state = this.state;
    if (state.phase === "awaiting_mode_selection") {
      if (!state.allowedModes.includes(mode)) return;
      this.set({
        phase: "ready",
        query: state.query,
        selectedMode: mode,
        modeSource: "user",
        suggestion: state.suggestion,
      });
      return;
    }
    if (state.phase === "suggesting_mode" || state.phase === "searching") return;
    this.set({
      phase: "ready",
      query: state.query,
      selectedMode: mode,
      modeSource: "user",
      suggestion: state.phase === "ready" ? state.suggestion : null,
    });
  }

  /** idle/ready/结果/错误态 → suggesting_mode；requires_user_selection 时停在 awaiting。
   *  @returns 本次建议是否仍有效且已写入状态（token 未 stale / 未 abort）。 */
  async requestSuggestion(): Promise<boolean> {
    const query = this.state.query;
    if (!query.trim()) return false;
    if (this.state.phase === "suggesting_mode" || this.state.phase === "searching") return false;
    const { token, signal } = this.begin();
    this.set({
      phase: "suggesting_mode",
      query,
      selectedMode: this.state.selectedMode,
      modeSource: this.state.modeSource,
    });
    try {
      const suggestion = await this.deps.suggestMode(query, signal);
      if (!this.isCurrent(token)) return false;
      this.applySuggestion(suggestion);
      return true;
    } catch (error) {
      if (!this.isCurrent(token) || isAbortError(error)) return false;
      this.settleAsyncError(token, error, null);
      return false;
    }
  }

  /**
   * 提交检索。awaiting_mode_selection 下为空操作（UI 同时禁用提交），
   * 保证问题/领域输入未经用户明确选择绝不发出 search。
   *
   * idle 路径：仅当 requestSuggestion 返回 true（建议仍属本次调用且已写入状态）
   * 时才读取 ready 并自动检索，防止旧 submit 在 setQuery 后继续新查询的状态。
   */
  async submit(): Promise<void> {
    const state = this.state;
    if (state.phase === "idle") {
      const applied = await this.requestSuggestion();
      if (!applied) return;
      const after = this.state;
      if (after.phase === "ready") {
        await this.startSearch(after.selectedMode);
      }
      return;
    }
    if (
      state.phase === "awaiting_mode_selection" ||
      state.phase === "suggesting_mode" ||
      state.phase === "searching"
    ) {
      return;
    }
    const mode = state.selectedMode;
    if (mode === null) return;
    await this.startSearch(mode);
  }

  private applySuggestion(suggestion: ModeSuggestionResponse): void {
    const { query, selectedMode, modeSource } = this.state;
    if (suggestion.requires_user_selection) {
      const allowed = sanitizeAllowedModes(suggestion.allowed_modes);
      const allowedModes = allowed.length > 0 ? allowed : [...ALL_MODES];
      // 只保留仍然适用的旧选择作为高亮；仍需用户再明确确认一次才离开 awaiting。
      const kept = selectedMode && allowedModes.includes(selectedMode) ? selectedMode : null;
      this.set({
        phase: "awaiting_mode_selection",
        query,
        selectedMode: kept,
        modeSource: kept ? modeSource : null,
        allowedModes,
        suggestion,
      });
      return;
    }
    if (suggestion.suggested_mode) {
      // 用户明确确认过的选择优先；建议只填空位或更新建议自己设置的 mode。
      if (selectedMode && modeSource === "user") {
        this.set({ phase: "ready", query, selectedMode, modeSource, suggestion });
        return;
      }
      this.set({
        phase: "ready",
        query,
        selectedMode: suggestion.suggested_mode,
        modeSource: "suggested",
        suggestion,
      });
      return;
    }
    if (selectedMode) {
      this.set({ phase: "ready", query, selectedMode, modeSource: modeSource ?? "user", suggestion });
      return;
    }
    // 置信度不足且无建议：保持输入不变，全部模式交由用户选择。
    this.set({
      phase: "awaiting_mode_selection",
      query,
      selectedMode: null,
      modeSource: null,
      allowedModes: sanitizeAllowedModes(suggestion.allowed_modes).length
        ? sanitizeAllowedModes(suggestion.allowed_modes)
        : [...ALL_MODES],
      suggestion,
    });
  }

  private async startSearch(mode: SearchMode): Promise<void> {
    const query = this.state.query;
    const modeSource = this.state.modeSource ?? "user";
    const { token, signal } = this.begin();
    this.set({ phase: "searching", query, selectedMode: mode, modeSource });
    try {
      const response = await this.deps.search(this.deps.buildRequest(query, mode), signal);
      if (!this.isCurrent(token)) return;
      this.set({ phase: classifySearchResponse(response), query, selectedMode: mode, modeSource, response });
    } catch (error) {
      this.settleAsyncError(token, error, mode);
    }
  }

  private settleAsyncError(token: number, error: unknown, mode: SearchMode | null): void {
    if (!this.isCurrent(token) || isAbortError(error)) return;
    const queryError = toQueryError(error);
    const { query, selectedMode, modeSource } = this.state;
    // 后端兜底拒绝（04 §10.2）：问题/领域未选组织方式时，回到 awaiting 而不是错误死胡同。
    if (mode !== null && queryError.code === "MODE_SELECTION_REQUIRED") {
      const fromDetails = sanitizeAllowedModes(queryError.details?.allowed_modes);
      const allowedModes: SearchMode[] = fromDetails.length > 0 ? fromDetails : ["timeline", "thematic"];
      const kept = allowedModes.includes(mode) ? mode : null;
      this.set({
        phase: "awaiting_mode_selection",
        query,
        selectedMode: kept,
        modeSource: kept ? modeSource : null,
        allowedModes,
        suggestion: null,
      });
      return;
    }
    this.set({
      phase: "error",
      query,
      selectedMode: mode ?? selectedMode,
      modeSource,
      error: queryError,
    });
  }

  private begin(): { token: number; signal: AbortSignal } {
    this.cancelInFlight();
    const controller = new AbortController();
    this.inFlight = controller;
    return { token: this.sequence, signal: controller.signal };
  }

  private cancelInFlight(): void {
    this.inFlight?.abort();
    this.inFlight = null;
    this.sequence += 1;
  }

  private isCurrent(token: number): boolean {
    return token === this.sequence;
  }

  private set(state: QueryState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }
}
