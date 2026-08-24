import { afterEach, describe, expect, it, vi } from "vitest";
import type { SearchRequest } from "../contracts";
import { makeSearchResponse, SYNTHETIC_QUERY } from "../testing/fixtures";
import { ApiClientError, search, suggestMode } from "./client";

const REQUEST: SearchRequest = {
  query: SYNTHETIC_QUERY,
  mode: "timeline",
  scope: { corpus_ids: ["syn_corpus_001"] },
  sort: null,
  cursor: null,
  page_size: 20,
  options: { include_generated_summaries: true, include_counter_evidence: true },
};

function stubFetch(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("search client", () => {
  it("返回生成契约中的 SearchResponse，而不是 unknown", async () => {
    const payload = makeSearchResponse();
    const mock = stubFetch(jsonResponse(200, payload));

    const result = await search(REQUEST);

    expect(result).toEqual(payload);
    // 类型化访问：编译期即保证字段存在。
    expect(result.request_id).toBe("req_syn_test");
    expect(result.overview.evidence_count).toBe(1);

    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url.endsWith("/api/v1/search")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(REQUEST);
  });

  it("非 2xx 且带统一 ErrorResponse 时抛出 ApiClientError", async () => {
    const errorBody = {
      request_id: "req_e",
      error: { code: "MODE_SELECTION_REQUIRED", message: "问题/领域尚未选择呈现方式。", retryable: false },
    };
    stubFetch(jsonResponse(400, errorBody));

    const error = await search(REQUEST).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiClientError);
    const apiError = error as ApiClientError;
    expect(apiError.status).toBe(400);
    expect(apiError.payload).toEqual(errorBody);
    expect(apiError.message).toBe("问题/领域尚未选择呈现方式。");
  });

  it("非 JSON 错误体兜底合成 ErrorResponse 形状", async () => {
    stubFetch(new Response("bad gateway", { status: 503 }));

    const error = await search(REQUEST).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiClientError);
    const apiError = error as ApiClientError;
    expect(apiError.payload.error.code).toBe("HTTP_503");
    expect(apiError.payload.error.retryable).toBe(true);
  });

  it("AbortSignal 透传给 fetch，供上层取消", async () => {
    const mock = stubFetch(jsonResponse(200, makeSearchResponse()));
    const controller = new AbortController();

    await search(REQUEST, controller.signal);

    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
  });
});

describe("suggestMode client", () => {
  it("POST 查询原文并返回 ModeSuggestionResponse", async () => {
    const suggestion = {
      suggested_mode: null,
      confidence: 0.91,
      requires_user_selection: true,
      allowed_modes: ["timeline", "thematic"],
      reason_code: "QUESTION_OR_DOMAIN",
    };
    const mock = stubFetch(jsonResponse(200, suggestion));

    const result = await suggestMode(REQUEST.query);

    expect(result).toEqual(suggestion);
    expect(result.requires_user_selection).toBe(true);
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url.endsWith("/api/v1/query-mode/suggest")).toBe(true);
    expect(JSON.parse(String(init.body))).toEqual({ query: REQUEST.query });
  });
});
