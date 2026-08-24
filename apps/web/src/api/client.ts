import type { ApiError, ModeSuggestionResponse, SearchRequest, SearchResponse } from "../contracts";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiClientError extends Error {
  constructor(public readonly payload: ApiError, public readonly status: number) {
    super(payload.error.message);
  }
}

function isApiError(payload: unknown): payload is ApiError {
  if (typeof payload !== "object" || payload === null) return false;
  const body = (payload as { error?: unknown }).error;
  if (typeof body !== "object" || body === null) return false;
  const { code, message } = body as { code?: unknown; message?: unknown };
  return typeof code === "string" && typeof message === "string";
}

// 服务器应始终返回统一 ErrorResponse；代理截断等场景下兜底合成，保证上层形状稳定。
function normalizeErrorPayload(payload: unknown, status: number): ApiError {
  if (isApiError(payload)) return payload;
  return {
    request_id: "",
    error: {
      code: `HTTP_${status}`,
      message: `请求失败（HTTP ${status}）`,
      retryable: status >= 500,
      details: {},
    },
  };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    throw new ApiClientError(normalizeErrorPayload(payload, response.status), response.status);
  }
  return payload as T;
}

export function suggestMode(query: string, signal?: AbortSignal): Promise<ModeSuggestionResponse> {
  return requestJson("/query-mode/suggest", {
    method: "POST",
    body: JSON.stringify({ query }),
    signal,
  });
}

export function search(payload: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
  return requestJson("/search", { method: "POST", body: JSON.stringify(payload), signal });
}
