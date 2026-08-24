import type { ApiError, ModeSuggestionResponse, SearchRequest } from "../contracts";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiClientError extends Error {
  constructor(public readonly payload: ApiError, public readonly status: number) {
    super(payload.error.message);
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    throw new ApiClientError(payload as ApiError, response.status);
  }
  return payload as T;
}

export function suggestMode(query: string): Promise<ModeSuggestionResponse> {
  return requestJson("/query-mode/suggest", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export function search(payload: SearchRequest): Promise<unknown> {
  return requestJson("/search", { method: "POST", body: JSON.stringify(payload) });
}
