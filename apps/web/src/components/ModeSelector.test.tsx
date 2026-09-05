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

describe("ModeSelector 可用性徽章", () => {
  it("普通环境：未接入模式标「尚未实现」，exact 标「当前可用」", () => {
    const html = renderToStaticMarkup(
      <ModeSelector
        value={null}
        onChange={() => {}}
        unavailableModes={["claim", "timeline", "thematic"]}
      />,
    );
    expect(html.match(/尚未实现/g)?.length).toBe(3);
    expect(html.match(/当前可用/g)?.length).toBe(1);
    expect(html).toContain("mode-badge--unavailable");
    expect(html).toContain("mode-badge--available");
  });

  it("徽章不改变可选性：未实现模式的 input 不因此 disabled", () => {
    const html = renderToStaticMarkup(
      <ModeSelector
        value={null}
        onChange={() => {}}
        unavailableModes={["claim", "timeline", "thematic"]}
      />,
    );
    expect(html).not.toContain("disabled");
  });

  it("demo/默认：不传 unavailableModes 时不渲染徽章", () => {
    const html = renderToStaticMarkup(<ModeSelector value="exact" onChange={() => {}} />);
    expect(html).not.toContain("mode-badge");
    expect(html).not.toContain("尚未实现");
    expect(html).not.toContain("当前可用");
  });
});
