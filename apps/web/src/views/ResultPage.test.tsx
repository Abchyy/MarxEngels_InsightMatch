import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { classifySearchResponse } from "../query/queryMachine";
import { ResultPage } from "./ResultPage";
import { dedupeThematicGroups, resolveThematicLabel } from "./ThematicGroups";
import {
  claimWithCounterResponse,
  exactEmptyResponse,
  exactEmptyWithWarningResponse,
  exactMultiHighlightResponse,
  exactSurrogateResponse,
  partialWithWarningsResponse,
  thematicDuplicateResponse,
  timelineDisputedUnknownResponse,
} from "../testing/resultFixtures";

const noop = () => {};

describe("classifySearchResponse", () => {
  it("Exact NO_EXACT_MATCH 进入 empty 而非 partial", () => {
    expect(classifySearchResponse(exactEmptyResponse())).toBe("empty");
  });

  it("Exact 空结果带 warning 仍为 empty，warning 由 UI 单独展示", () => {
    expect(classifySearchResponse(exactEmptyWithWarningResponse())).toBe("empty");
  });
});

describe("ResultPage 组合渲染", () => {
  it("Claim 证据不足整页只出现一次", () => {
    const response = claimWithCounterResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="claim"
        phase="partial"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html.match(/证据不足/g)?.length).toBe(1);
    expect(html).toContain("相反材料段落，必须可见");
  });

  it("Exact 空结果标题为未找到结果，非部分结果", () => {
    const response = exactEmptyResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="exact"
        phase="empty"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
        onSuggestModeSwitch={noop}
      />,
    );
    expect(html).toContain("未找到结果");
    expect(html).not.toContain("部分结果");
    expect(html).toContain("改用语义检索");
  });

  it("Exact 空结果带 warning 仍显示 warning", () => {
    const response = exactEmptyWithWarningResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="exact"
        phase="empty"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html).toContain("RERANKER_UNAVAILABLE");
  });

  it("partial 响应 warnings 与 insufficiency 均在概览首屏", () => {
    const response = partialWithWarningsResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="claim"
        phase="partial"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html).toContain("部分结果");
    expect(html).toContain("RERANKER_UNAVAILABLE");
    expect(html).toContain("证据不足");
  });
});

describe("Exact 视图控制", () => {
  it("提供 relevance/document_order 排序选项", () => {
    const response = exactMultiHighlightResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="exact"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort="document_order"
        onExactSortChange={noop}
      />,
    );
    expect(html).toContain("按相关度");
    expect(html).toContain("按卷页顺序");
    expect(html).toContain("不会自动重新查询");
  });

  it("onExactSortChange 可被调用且不隐含 search", () => {
    const onSort = vi.fn();
    const response = exactMultiHighlightResponse();
    renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="exact"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={onSort}
      />,
    );
    expect(onSort).not.toHaveBeenCalled();
  });
});

describe("Timeline 视图控制", () => {
  it("隐藏机器阶段摘要时不渲染 summary 段落", () => {
    const response = timelineDisputedUnknownResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="timeline"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
        timelineShowSummaries={false}
      />,
    );
    expect(html).toContain("显示机器阶段摘要");
    expect(html).not.toContain("2001 阶段机器摘要");
  });

  it("disputed/unknown 使用明确文字", () => {
    const response = timelineDisputedUnknownResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="timeline"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html).toContain("日期有争议");
    expect(html).toContain("时间未知");
  });
});

describe("Thematic 视图控制", () => {
  it("关闭机器标签后使用主题 1、主题 2", () => {
    const response = thematicDuplicateResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="thematic"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
        thematicShowMachineLabels={false}
      />,
    );
    expect(html).toContain("主题 1");
    expect(html).toContain("主题 2");
    expect(html).not.toContain("【合成】主题 A");
    expect(html).toContain("其他相关材料");
    expect(html).toContain("语义聚类不是唯一权威思想分类");
  });

  it("重复 evidence 只渲染一次", () => {
    const response = thematicDuplicateResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="thematic"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html.match(/共享证据，只应出现一次/g)?.length).toBe(1);
  });
});

describe("resolveThematicLabel", () => {
  it("other_related 始终保留原标签", () => {
    expect(
      resolveThematicLabel(
        { group_id: "g", group_type: "other_related", label: "其他相关材料" },
        0,
        false,
      ),
    ).toBe("其他相关材料");
  });
});

describe("dedupeThematicGroups", () => {
  it("跨组重复 id 只在第一组保留", () => {
    const groups = thematicDuplicateResponse().groups ?? [];
    const deduped = dedupeThematicGroups(groups);
    expect(deduped.find((g) => g.group_id === "g_theme_b")?.evidence_ids).not.toContain("ev_syn_shared");
  });
});

describe("exact 高亮与 surrogate fixture", () => {
  it("exact fixture offsets 与正文一致", () => {
    const response = exactMultiHighlightResponse();
    const item = response.evidence![0]!;
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="exact"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html).toContain("命中 3 次");
    expect(html.match(/<mark>协作<\/mark>/g)?.length).toBe(3);
  });

  it("surrogate 响应高亮正确", () => {
    const response = exactSurrogateResponse();
    const html = renderToStaticMarkup(
      <ResultPage
        response={response}
        selectedMode="exact"
        phase="success"
        matchQuery={response.query.trim()}
        exactSort={null}
        onExactSortChange={noop}
      />,
    );
    expect(html).toContain("<mark>劳动</mark>");
  });
});
