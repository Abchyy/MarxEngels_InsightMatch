import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HighlightedText } from "./HighlightedText";
import { EvidenceCard } from "./EvidenceCard";
import { makeEvidence } from "../testing/fixtures";
import { exactMultiHighlightResponse, exactSurrogateResponse } from "../testing/resultFixtures";

describe("HighlightedText 渲染", () => {
  it("使用 mark 元素，不使用 dangerouslySetInnerHTML", () => {
    const item = exactMultiHighlightResponse().evidence![0]!;
    const html = renderToStaticMarkup(
      <HighlightedText
        text={item.verified_text}
        offsets={item.match_offsets}
        matchQuery="协作"
      />,
    );
    expect(html).toContain("<mark>协作</mark>");
    expect(html).not.toContain("dangerouslySetInnerHTML");
    expect(html.match(/<mark/g)?.length).toBe(3);
  });

  it("𠮷劳动 surrogate 高亮", () => {
    const item = exactSurrogateResponse().evidence![0]!;
    const html = renderToStaticMarkup(
      <HighlightedText text={item.verified_text} offsets={item.match_offsets} matchQuery="劳动" />,
    );
    expect(html).toContain("<mark>劳动</mark>");
    expect(html).not.toContain("<mark>𠮷劳动</mark>");
  });
});

describe("EvidenceCard", () => {
  it("counter 标签可见；不渲染 search_text", () => {
    const html = renderToStaticMarkup(
      <EvidenceCard
        evidence={makeEvidence({
          support_label: "counter",
          verified_text: "【合成】相反材料正文。",
        })}
      />,
    );
    expect(html).toContain("相反材料");
    expect(html).not.toContain("search_text");
  });
});
