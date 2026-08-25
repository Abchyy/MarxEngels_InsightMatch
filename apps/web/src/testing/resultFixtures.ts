import type { SearchResponse } from "../contracts";
import { makeEvidence, makeSearchResponse, SYNTHETIC_QUERY } from "./fixtures";

const EXACT_TEXT = "【合成】协作劳动与协作交往在本段出现两次：协作是关键词。";
const EXACT_QUERY = "协作";

export const exactMultiHighlightResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "exact",
    query: EXACT_QUERY,
    evidence: [
      makeEvidence({
        evidence_id: "ev_syn_exact_001",
        verified_text: EXACT_TEXT,
        match_type: "exact",
        exact_match_count: 3,
        match_offsets: [4, 9, 21],
        support_label: null,
        rank_reasons: ["逐字命中"],
      }),
    ],
    overview: { evidence_count: 1, work_count: 1, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });

export const exactEmptyResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "exact",
    query: EXACT_QUERY,
    evidence: [],
    groups: [],
    insufficiency: {
      code: "NO_EXACT_MATCH",
      message: "【合成】在当前范围内未发现该词的逐字命中。",
    },
    overview: { evidence_count: 0, work_count: 0, volume_count: 0, result_note: "以下组织只基于列出的证据。" },
  });

export const exactEmptyWithWarningResponse = (): SearchResponse =>
  makeSearchResponse({
    ...exactEmptyResponse(),
    warnings: [{ code: "RERANKER_UNAVAILABLE", message: "【合成】重排暂不可用。", stage: "rerank" }],
  });

export const exactSurrogateResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "exact",
    query: "劳动",
    evidence: [
      makeEvidence({
        evidence_id: "ev_syn_surrogate",
        verified_text: "𠮷劳动",
        match_type: "exact",
        exact_match_count: 1,
        match_offsets: [1],
        support_label: null,
      }),
    ],
    overview: { evidence_count: 1, work_count: 1, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });

export const claimWithCounterResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "claim",
    insufficiency: { code: "INSUFFICIENT_SUPPORT", message: "【合成】支撑材料不足以证明该观点。" },
    groups: [
      {
        group_id: "g_direct",
        group_type: "supporting",
        label: "直接支撑",
        evidence_ids: ["ev_syn_direct"],
      },
      {
        group_id: "g_counter",
        group_type: "counter",
        label: "相反材料",
        evidence_ids: ["ev_syn_counter"],
      },
    ],
    evidence: [
      makeEvidence({
        evidence_id: "ev_syn_direct",
        support_label: "direct",
        verified_text: "【合成数据】直接支撑段落。",
      }),
      makeEvidence({
        evidence_id: "ev_syn_counter",
        support_label: "counter",
        verified_text: "【合成数据】相反材料段落，必须可见。",
        author: "合成作者 B",
      }),
    ],
    overview: { evidence_count: 2, work_count: 2, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });

export const timelineDisputedUnknownResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "timeline",
    groups: [
      {
        group_id: "g_known",
        group_type: "period",
        label: "2001 阶段",
        date_start: "2001",
        date_end: "2001",
        date_precision: "year",
        summary: "【合成】2001 阶段机器摘要。",
        evidence_ids: ["ev_syn_t_001"],
      },
      {
        group_id: "g_disputed",
        group_type: "period",
        label: "争议阶段",
        date_start: "2003?",
        date_end: null,
        date_precision: "disputed",
        evidence_ids: ["ev_syn_t_002"],
      },
      {
        group_id: "g_unknown",
        group_type: "unknown",
        label: "时间待考",
        date_start: null,
        date_end: null,
        date_precision: "unknown",
        evidence_ids: ["ev_syn_t_003"],
      },
    ],
    evidence: [
      makeEvidence({ evidence_id: "ev_syn_t_001", work_date_start: "2001" }),
      makeEvidence({
        evidence_id: "ev_syn_t_002",
        work_title: "[合成] 争议材料",
        work_date_start: "2003?",
        date_precision: "disputed",
      }),
      makeEvidence({
        evidence_id: "ev_syn_t_003",
        work_title: "[合成] 未知日期材料",
        work_date_start: null,
        date_precision: "unknown",
      }),
    ],
    overview: { evidence_count: 3, work_count: 3, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });

export const thematicDuplicateResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "thematic",
    query: SYNTHETIC_QUERY,
    classification_notice: "【合成提示】语义聚类不是唯一权威思想分类。",
    groups: [
      {
        group_id: "g_theme_a",
        group_type: "theme",
        label: "【合成】主题 A",
        summary: "【合成】主题 A 的机器归纳说明。",
        evidence_ids: ["ev_syn_shared", "ev_syn_a_only"],
      },
      {
        group_id: "g_theme_b",
        group_type: "theme",
        label: "【合成】主题 B",
        summary: "【合成】主题 B 说明。",
        evidence_ids: ["ev_syn_shared", "ev_syn_b_only"],
      },
      {
        group_id: "g_other",
        group_type: "other_related",
        label: "其他相关材料",
        summary: "【合成】离群材料。",
        evidence_ids: ["ev_syn_other"],
      },
    ],
    evidence: [
      makeEvidence({ evidence_id: "ev_syn_shared", verified_text: "【合成】共享证据，只应出现一次。" }),
      makeEvidence({ evidence_id: "ev_syn_a_only", verified_text: "【合成】仅主题 A。" }),
      makeEvidence({ evidence_id: "ev_syn_b_only", verified_text: "【合成】仅主题 B。" }),
      makeEvidence({ evidence_id: "ev_syn_other", verified_text: "【合成】其他相关。" }),
    ],
    overview: { evidence_count: 4, work_count: 4, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });

export const partialWithWarningsResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "claim",
    warnings: [{ code: "RERANKER_UNAVAILABLE", message: "【合成】重排服务暂不可用。", stage: "rerank" }],
    insufficiency: { code: "PARTIAL", message: "【合成】部分降级。" },
    evidence: [makeEvidence()],
    overview: { evidence_count: 1, work_count: 1, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });

export const timelineCollapsibleWorkResponse = (): SearchResponse =>
  makeSearchResponse({
    mode: "timeline",
    groups: [
      {
        group_id: "g_period",
        group_type: "period",
        label: "2001",
        date_start: "2001",
        date_precision: "year",
        evidence_ids: ["ev_syn_w1", "ev_syn_w2"],
      },
    ],
    evidence: [
      makeEvidence({
        evidence_id: "ev_syn_w1",
        work_title: "[合成] 同一著作",
        verified_text: "【合成】第一段。",
      }),
      makeEvidence({
        evidence_id: "ev_syn_w2",
        work_title: "[合成] 同一著作",
        verified_text: "【合成】第二段。",
      }),
    ],
    overview: { evidence_count: 2, work_count: 1, volume_count: 1, result_note: "以下组织只基于列出的证据。" },
  });
