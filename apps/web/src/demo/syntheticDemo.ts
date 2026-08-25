import type { SearchMode, SearchRequest, SearchScope } from "../contracts";
import type { ExactSort } from "../views/ExactResultList";

export const PRODUCTION_CORPUS_ID = "marx_engels_collected_works_cn";
export const SYNTHETIC_DEMO_CORPUS_ID = "synthetic_mecw_test";
export const SYNTHETIC_DEMO_BANNER = "合成数据演示，不是马克思恩格斯原典";

export interface SyntheticDemoExample {
  mode: SearchMode;
  query: string;
  label: string;
}

export const SYNTHETIC_DEMO_EXAMPLES: readonly SyntheticDemoExample[] = [
  { mode: "exact", query: "劳动", label: "精确检索" },
  { mode: "claim", query: "协作劳动会改变群体关系", label: "观点语义检索" },
  { mode: "timeline", query: "公共讨论如何变化", label: "按时间呈现" },
  { mode: "thematic", query: "生产关系与制度安排", label: "按思想结构呈现" },
];

export function isSyntheticDemoMode(
  flag: string | boolean | undefined = import.meta.env.VITE_DEMO_MODE,
): boolean {
  return flag === true || flag === "true";
}

export function defaultSearchScope(demoMode: boolean): SearchScope {
  return {
    corpus_ids: [demoMode ? SYNTHETIC_DEMO_CORPUS_ID : PRODUCTION_CORPUS_ID],
    edition_ids: [],
    volume_ids: [],
    work_ids: [],
    authors: [],
    content_types: ["main_text", "author_note"],
  };
}

export function buildSearchRequest(
  query: string,
  mode: SearchMode,
  exactSort: ExactSort | null,
  demoMode: boolean,
): SearchRequest {
  return {
    query,
    mode,
    scope: defaultSearchScope(demoMode),
    sort: mode === "exact" ? exactSort : null,
    cursor: null,
    page_size: 20,
    options: { include_generated_summaries: true, include_counter_evidence: true },
  };
}
