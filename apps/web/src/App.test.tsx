import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SearchApp } from "./App";
import { SYNTHETIC_DEMO_BANNER, SYNTHETIC_DEMO_EXAMPLES } from "./demo/syntheticDemo";

describe("SearchApp demo chrome", () => {
  it("demo mode 显示警告条和四个示例查询", () => {
    const html = renderToStaticMarkup(<SearchApp demoMode={true} />);
    expect(html).toContain(SYNTHETIC_DEMO_BANNER);
    expect(html).toContain('class="demo-banner"');
    expect(html).toContain("合成测试语料");
    for (const example of SYNTHETIC_DEMO_EXAMPLES) {
      expect(html).toContain(example.query);
      expect(html).toContain(example.label);
    }
  });

  it("普通模式不显示 demo banner 或示例查询", () => {
    const html = renderToStaticMarkup(<SearchApp demoMode={false} />);
    expect(html).not.toContain(SYNTHETIC_DEMO_BANNER);
    expect(html).not.toContain("demo-banner");
    expect(html).not.toContain("demo-examples");
    expect(html).toContain("马克思恩格斯文集");
    expect(html).toContain("未经人工校勘");
    expect(html).not.toContain("协作劳动会改变群体关系");
    expect(html).not.toContain("公共讨论如何变化");
    expect(html).not.toContain("生产关系与制度安排");
  });
});
