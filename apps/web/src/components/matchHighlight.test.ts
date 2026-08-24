import { describe, expect, it } from "vitest";
import {
  highlightedPlainText,
  parseMatchSpans,
  toCodePoints,
} from "./matchHighlight";

describe("parseMatchSpans（起始码点 + query 长度）", () => {
  const text = "【合成】协作劳动与协作交往在本段出现两次：协作是关键词。";
  const query = "协作";

  it("单次命中 offsets=[N] 能高亮", () => {
    const spans = parseMatchSpans(text, [4], query);
    expect(spans).toEqual([{ start: 4, end: 6 }]);
    expect(highlightedPlainText(text, [4], query)).toBe(text);
  });

  it("多次命中 offsets=[N1,N2] 分别高亮，不把中间文本整体高亮", () => {
    const spans = parseMatchSpans(text, [4, 9], query);
    expect(spans).toEqual([
      { start: 4, end: 6 },
      { start: 9, end: 11 },
    ]);
    const html = highlightedPlainText(text, [4, 9], query);
    expect(html).toBe(text);
    expect(html.match(/协作/g)?.length).toBe(3);
  });

  it("无效、越界、重复偏移安全忽略", () => {
    expect(parseMatchSpans(text, [4, 4, 999, -1, NaN as unknown as number], query)).toEqual([
      { start: 4, end: 6 },
    ]);
  });

  it("query trim 仅用于匹配长度，不改写显示 query", () => {
    expect(parseMatchSpans(text, [4], "  协作  ")).toEqual([{ start: 4, end: 6 }]);
  });

  it("𠮷劳动 查询 劳动、offsets=[1] 时正确高亮劳动", () => {
    const surrogateText = "𠮷劳动";
    expect(toCodePoints(surrogateText)).toEqual(["𠮷", "劳", "动"]);
    const spans = parseMatchSpans(surrogateText, [1], "劳动");
    expect(spans).toEqual([{ start: 1, end: 3 }]);
    expect(highlightedPlainText(surrogateText, [1], "劳动")).toBe(surrogateText);
  });

  it("复制/渲染后的完整文本与 verified_text 一致", () => {
    const offsets = [4, 9, 21];
    expect(highlightedPlainText(text, offsets, query)).toBe(text);
  });
});
