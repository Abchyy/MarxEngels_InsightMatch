import type { Evidence, SearchResponse } from "../contracts";

/** 测试默认查询：明确合成，不对应任何真实检索意图。 */
export const SYNTHETIC_QUERY = "【合成查询】协作如何塑造交往方式";

/**
 * 全部字段均为合成数据，禁止当作真实原典引文或正式出处使用；
 * 与《马克思恩格斯文集》的实际文本、作者、著作、版本、页码无关。
 */
export function makeEvidence(overrides: Partial<Evidence> = {}): Evidence {
  return {
    evidence_id: "ev_syn_early_001",
    verified_text: "【合成数据，非原典】协作劳动会改变群体之间的关系，劳动也会塑造新的交往方式。",
    content_type: "main_text",
    author: "合成作者（非历史人物）",
    work_title: "[合成] 早期协作材料",
    corpus_name: "合成测试语料（全部文本均为虚构）",
    edition_label: "合成测试版（禁止引用）",
    volume_no: 1,
    work_date_start: "2001",
    work_date_end: "2001",
    date_precision: "year",
    printed_pages: ["1"],
    pdf_pages: [10],
    match_type: "semantic",
    support_label: "direct",
    rank_reasons: ["合成排序理由"],
    ...overrides,
  };
}

export function makeSearchResponse(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    request_id: "req_syn_test",
    mode: "timeline",
    query: SYNTHETIC_QUERY,
    scope_snapshot: { corpus_ids: ["syn_corpus_001"] },
    release: { data_version: "data_syn_test", index_version: "idx_syn_test" },
    overview: {
      evidence_count: 1,
      work_count: 1,
      volume_count: 1,
      result_note: "以下组织只基于列出的证据。",
    },
    groups: [],
    evidence: [makeEvidence()],
    next_cursor: null,
    insufficiency: null,
    warnings: [],
    ...overrides,
  };
}
