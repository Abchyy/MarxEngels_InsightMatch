import { describe, expect, it } from "vitest";
import {
  PRODUCTION_CORPUS_ID,
  SYNTHETIC_DEMO_BANNER,
  SYNTHETIC_DEMO_CORPUS_ID,
  SYNTHETIC_DEMO_EXAMPLES,
  buildSearchRequest,
  defaultSearchScope,
  isSyntheticDemoMode,
} from "./syntheticDemo";

describe("synthetic demo scope", () => {
  it("demo mode 使用 synthetic_mecw_test", () => {
    expect(defaultSearchScope(true).corpus_ids).toEqual([SYNTHETIC_DEMO_CORPUS_ID]);
    expect(
      buildSearchRequest("劳动", "exact", null, true).scope.corpus_ids,
    ).toEqual(["synthetic_mecw_test"]);
  });

  it("普通模式仍使用正式 corpus scope", () => {
    expect(defaultSearchScope(false).corpus_ids).toEqual([PRODUCTION_CORPUS_ID]);
    expect(
      buildSearchRequest("劳动", "exact", null, false).scope.corpus_ids,
    ).toEqual(["marx_engels_collected_works_cn"]);
  });

  it("VITE_DEMO_MODE 只有显式 true 才启用", () => {
    expect(isSyntheticDemoMode("true")).toBe(true);
    expect(isSyntheticDemoMode(true)).toBe(true);
    expect(isSyntheticDemoMode("false")).toBe(false);
    expect(isSyntheticDemoMode(undefined)).toBe(false);
    expect(isSyntheticDemoMode("")).toBe(false);
  });
});

describe("synthetic demo examples", () => {
  it("包含四个现有测试查询", () => {
    expect(SYNTHETIC_DEMO_BANNER).toBe("合成数据演示，不是马克思恩格斯原典");
    expect(SYNTHETIC_DEMO_EXAMPLES.map((item) => [item.mode, item.query])).toEqual([
      ["exact", "劳动"],
      ["claim", "协作劳动会改变群体关系"],
      ["timeline", "公共讨论如何变化"],
      ["thematic", "生产关系与制度安排"],
    ]);
  });
});
