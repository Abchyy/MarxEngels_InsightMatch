import type { DatePrecision, SupportLabel } from "../contracts";

export const SUPPORT_LABELS: Record<SupportLabel, string> = {
  direct: "直接支撑",
  indirect: "间接相关",
  counter: "相反材料",
  context_only: "语境相关",
  irrelevant: "不相关",
};

export const MATCH_TYPE_LABELS: Record<string, string> = {
  exact: "逐字命中",
  semantic: "语义相关",
  fts: "关键词命中",
};

export const DATE_PRECISION_LABELS: Record<DatePrecision, string> = {
  day: "精确到日",
  month: "精确到月",
  year: "精确到年",
  range: "日期区间",
  approximate: "约数日期",
  disputed: "日期有争议",
  unknown: "时间未知",
};

export const THEMATIC_CLASSIFICATION_NOTICE =
  "语义聚类不是唯一权威思想分类；以下主题组仅反映本次检索的语义组织。";

export function formatDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
  precision: DatePrecision | null | undefined,
): string {
  const tag = precision ? DATE_PRECISION_LABELS[precision] : DATE_PRECISION_LABELS.unknown;
  if (precision === "unknown" || (!start && !end)) {
    return `时间待考（${tag}）`;
  }
  if (precision === "range" && start && end) {
    return `${start} — ${end}（${tag}）`;
  }
  if (precision === "approximate" && start) {
    return `约 ${start}（${tag}）`;
  }
  if (precision === "disputed") {
    const base = start ?? end ?? "—";
    return `${base}（${tag}）`;
  }
  if (start && end && start !== end) {
    return `${start} — ${end}（${tag}）`;
  }
  return `${start ?? end ?? "—"}（${tag}）`;
}
