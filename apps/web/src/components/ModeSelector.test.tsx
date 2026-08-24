import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ModeSelector } from "./ModeSelector";

describe("ModeSelector class 组合", () => {
  it("selected 与 disabled 可同时生效（空格分隔，分别命中 CSS）", () => {
    const html = renderToStaticMarkup(
      <ModeSelector value="timeline" allowedModes={["timeline"]} disabled onChange={() => {}} />,
    );
    expect(html).toContain('class="selected disabled"');
    expect(html).not.toContain("selecteddisabled");
  });

  it("仅选中：class 恰好为 selected，不残留空拼接", () => {
    const html = renderToStaticMarkup(<ModeSelector value="exact" onChange={() => {}} />);
    expect(html).toContain('class="selected"');
    expect(html).not.toContain("disabled");
  });

  it("仅禁用：不可用模式带 disabled class 且 input disabled", () => {
    const html = renderToStaticMarkup(
      <ModeSelector value={null} allowedModes={["timeline", "thematic"]} onChange={() => {}} />,
    );
    expect(html).not.toContain("selected");
    expect(html).toContain('class="disabled"');
    expect(html).toContain("disabled");
  });

  it("awaiting 场景：允许的模式保持可选，其余禁用", () => {
    const html = renderToStaticMarkup(
      <ModeSelector value={null} allowedModes={["timeline", "thematic"]} onChange={() => {}} />,
    );
    // 四个选项中两个 disabled；timeline/thematic 的 label 无 class
    const disabledLabels = html.match(/class="disabled"/g) ?? [];
    expect(disabledLabels).toHaveLength(2);
  });
});
