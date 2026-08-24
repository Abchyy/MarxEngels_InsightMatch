/** 将字符串拆为 Unicode 码点序列，与 Python 3 str 索引对齐。 */
export function toCodePoints(text: string): string[] {
  return [...text];
}

/**
 * 公共契约语义：match_offsets 为各命中的起始码点位置（非 start/end 对）。
 * matchQuery 仅 trim 首尾空白用于计算匹配长度，不改写显示用 query。
 */
export function parseMatchSpans(
  text: string,
  offsets: number[] | undefined,
  matchQuery: string,
): Array<{ start: number; end: number }> {
  const trimmedQuery = matchQuery.trim();
  if (!offsets?.length || !trimmedQuery) return [];

  const cps = toCodePoints(text);
  const queryCps = toCodePoints(trimmedQuery);
  const queryLen = queryCps.length;
  if (queryLen === 0) return [];

  const expected = queryCps.join("");
  const spans: Array<{ start: number; end: number }> = [];
  const seenStarts = new Set<number>();

  for (const raw of offsets) {
    if (!Number.isInteger(raw)) continue;
    const start = raw;
    if (start < 0 || start >= cps.length) continue;
    if (seenStarts.has(start)) continue;

    const end = start + queryLen;
    if (end > cps.length) continue;

    const slice = cps.slice(start, end).join("");
    if (slice !== expected) continue;

    const overlaps = spans.some((s) => start < s.end && end > s.start);
    if (overlaps) continue;

    spans.push({ start, end });
    seenStarts.add(start);
  }

  return spans.sort((a, b) => a.start - b.start);
}

/** 拼接高亮后的纯文本（无 mark 标签），用于断言与 verified_text 一致。 */
export function highlightedPlainText(
  text: string,
  offsets: number[] | undefined,
  matchQuery: string,
): string {
  const cps = toCodePoints(text);
  const spans = parseMatchSpans(text, offsets, matchQuery);
  if (spans.length === 0) return text;

  const parts: string[] = [];
  let cursor = 0;
  for (const span of spans) {
    parts.push(cps.slice(cursor, span.start).join(""));
    parts.push(cps.slice(span.start, span.end).join(""));
    cursor = span.end;
  }
  parts.push(cps.slice(cursor).join(""));
  return parts.join("");
}
