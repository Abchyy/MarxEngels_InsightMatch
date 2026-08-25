import type { ReactNode } from "react";
import { parseMatchSpans, toCodePoints } from "./matchHighlight";

interface Props {
  text: string;
  /** 各命中起始码点位置 */
  offsets?: number[];
  /** 仅 trim 首尾空白后用于计算匹配长度 */
  matchQuery: string;
}

export function HighlightedText({ text, offsets, matchQuery }: Props) {
  const cps = toCodePoints(text);
  const spans = parseMatchSpans(text, offsets, matchQuery);
  if (spans.length === 0) return <>{text}</>;

  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start > cursor) {
      nodes.push(cps.slice(cursor, span.start).join(""));
    }
    nodes.push(
      <mark key={`${span.start}:${span.end}`}>{cps.slice(span.start, span.end).join("")}</mark>,
    );
    cursor = span.end;
  }
  if (cursor < cps.length) {
    nodes.push(cps.slice(cursor).join(""));
  }
  return <>{nodes}</>;
}

export { parseMatchSpans, highlightedPlainText, toCodePoints } from "./matchHighlight";
