# 四条检索管线与证据服务技术规范

**Document ID:** RETRIEVAL-SPEC-03
**Version:** V1.0
**Parent document:** `Marx_Engels_Text_Retrieval_Assistant_Technical_Design_V1.1.md`
**Dependencies:** `01_Corpus_Processing_and_Construction_Specification_V1.0.md`, `02_Data_Storage_and_Indexing_Specification_V1.0.md`

---

## 1. 目标

本文将四条业务管线落实为可独立实现、独立测试的后台组件，并定义共享候选对象、范围校验、融合、重排、证据门、原文回填和审计协议。

四条管线：

1. `exact`：词语精确检索。
2. `claim`：观点语义检索。
3. `timeline`：问题/领域的时间序列检索。
4. `thematic`：问题/领域的思想结构检索。

---

## 2. 模块边界

```text
QueryRouter
  └── SearchPipeline
      ├── ExactPipeline
      ├── ClaimPipeline
      ├── TimelinePipeline
      └── ThematicPipeline

Shared Services
  ├── ScopeService
  ├── ExactSearchIndex
  ├── LexicalIndex
  ├── VectorIndex
  ├── FusionService
  ├── Reranker
  ├── ClusteringService
  ├── EvidenceService
  └── AuditService
```

规则：

- 管线不得直接访问前端状态。
- 管线依赖存储接口，不依赖 SQLite/LanceDB 的具体连接对象。
- EvidenceService 是唯一可生成正式 `Evidence` 展示对象的模块。
- 模型适配器不得返回可直接展示的原文或出处字段。
- 排序参数全部进入版本化配置并写入审计日志。

---

## 3. 公共领域对象

### 3.1 `SearchRequest`

```python
from enum import StrEnum
from pydantic import BaseModel, Field


class SearchMode(StrEnum):
    EXACT = "exact"
    CLAIM = "claim"
    TIMELINE = "timeline"
    THEMATIC = "thematic"


class SearchScope(BaseModel):
    corpus_ids: list[str] = Field(min_length=1)
    edition_ids: list[str] = Field(default_factory=list)
    volume_ids: list[str] = Field(default_factory=list)
    work_ids: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    content_types: list[str] = Field(
        default_factory=lambda: ["main_text", "author_note"]
    )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: SearchMode
    scope: SearchScope
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
```

### 3.2 `Candidate`

```python
class Candidate(BaseModel):
    evidence_id: str
    retrieval_unit_ids: list[str]
    channels: list[str]
    exact_match_count: int | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    support_label: str | None = None
    exclusion_reasons: list[str] = Field(default_factory=list)
    rank_reasons: list[str] = Field(default_factory=list)
```

`Candidate` 是内部对象，不包含最终展示引用。多个 retrieval units 命中同一 passage 时必须合并成一个 candidate。

### 3.3 `Evidence`

```python
class Evidence(BaseModel):
    evidence_id: str
    verified_text: str
    content_type: str
    author: str
    work_title: str
    corpus_name: str
    edition_label: str
    volume_no: int
    work_date_start: str | None
    work_date_end: str | None
    date_precision: str
    printed_pages: list[str]
    pdf_pages: list[int]
    prev_evidence_id: str | None
    next_evidence_id: str | None
    match_type: str
    support_label: str | None
    rank_reasons: list[str]
```

该对象只能由 EvidenceService 使用 SQLite 权威字段构建。

---

## 4. 查询路由

### 4.1 路由职责

QueryRouter 只建议模式，不替用户作不可见决定：

- 短词、固定短语或引号内容：建议 `exact`。
- 完整判断、论断或“这一观点是否有依据”：建议 `claim`。
- 疑问句、主题或领域：要求用户在 `timeline` 与 `thematic` 之间选择。
- 置信度低：返回所有适用选项。

### 4.2 响应

```json
{
  "suggested_mode": "exact",
  "confidence": 0.82,
  "requires_user_selection": false,
  "alternatives": ["claim"],
  "reason_code": "SHORT_TERM"
}
```

用户明确传入 `mode` 后，后端不得再次静默改为其他模式。

---

## 5. 公共运行阶段

所有管线执行：

1. 请求参数校验。
2. ScopeService 解析并固化范围快照。
3. 绑定当前 `data_version / index_version / model_versions`。
4. 执行管线专属召回和组织。
5. EvidenceService 执行证据门和回填。
6. 分页或分组封装。
7. AuditService 记录候选轨迹、排除原因、结果和耗时。

### 5.1 ScopeService

输入：用户 scope。
输出：只包含已发布对象的 `ResolvedScope`。

必须检查：

- corpus 存在且已发布。
- edition 属于指定 corpus。
- volume 属于指定 edition。
- work 属于指定 volume。
- 作者和内容类型为允许值。
- 空 volume/work 列表表示当前上级范围下的全部已发布内容，不表示无范围。

不合法层级组合返回 `INVALID_SCOPE`，不能自动删除冲突条件后继续查询。

---

## 6. 管线一：词语精确检索

### 6.1 输入规则

- `query` 去除输入框首尾空白后不能为空。
- 内部保留原始查询和实际匹配查询。
- 不做同义词、繁简体、大小写、旧译名或标点替换。
- V1 最大长度 500 字符；超限返回参数错误。

### 6.2 算法

```text
resolved_scope = resolve_scope(request.scope)
query = trim_outer_whitespace(request.query)

if length(query) <= 2:
    ids = sqlite_exact_scan(query, resolved_scope)
else:
    ids = optional_trigram_candidates(query, resolved_scope)
    ids = verify_each_with_instr(ids, query)
    if accelerator_not_equivalent_or_disabled:
        ids = sqlite_exact_scan(query, resolved_scope)

candidates = count_occurrences_and_build_candidates(ids)
candidates = sort(exact_match_count desc, volume_no asc, printed_page asc)
return evidence_service.hydrate(candidates, resolved_scope)
```

`sqlite_exact_scan` 的核心条件为 `instr(verified_text, :query) > 0`。

### 6.3 命中计数

命中次数必须按非重叠还是重叠匹配形成明确规则。V1 建议使用非重叠匹配，并在测试中固定。例如“人人”查询“人”返回 2 次。

计数仅用于排序和展示，是否入选只由逐字出现决定。

### 6.4 排序

默认：

1. 命中次数降序。
2. 单段命中密度降序。
3. 卷号升序。
4. 著作顺序升序。
5. 段落顺序升序。

可选 `document_order` 排序直接按卷、著作、段落顺序。

### 6.5 无结果

返回：

```json
{
  "insufficiency": {
    "code": "NO_EXACT_MATCH",
    "message": "在当前范围内未发现该词语的逐字命中。"
  }
}
```

不得自动改走语义检索。前端可以提供“改用观点语义检索”按钮，由用户主动触发新请求。

---

## 7. 管线二：观点语义检索

### 7.1 目标

找到能够直接支撑、间接回应或反驳用户观点的原文，并优先展示支撑关系最明确的证据。

### 7.2 候选召回

并行执行：

- VectorIndex：原查询 embedding 的 Top K 语义候选。
- LexicalIndex：原查询和经过审计的核心概念的 Top K 关键词候选。

查询理解可以抽取核心概念，但必须保留原查询作为主语义输入。不得让模型生成多个新观点替换原观点。

### 7.3 RRF 融合

```text
rrf_score(document) = Σ 1 / (k + rank_channel(document))
```

建议初始 `k=60`，但它是配置项，必须通过题集确定。未出现在某通道的候选不贡献该通道分数。

### 7.4 去重与多样性

- retrieval unit 先按 `evidence_id` 合并。
- 完全相同 `text_hash` 的同版本重复候选折叠。
- 同一著作的连续相邻段不得无限占据 Top N；可采用 per-work cap 或 MMR。
- 同文异版不得删除，只能在界面折叠并保留各自出处。

### 7.5 支撑关系重排

重排器输入：用户原观点、单个 `verified_text` 或明确标注的检索辅助上下文。输出：

```json
{
  "evidence_id": "ev_...",
  "support_label": "direct",
  "support_score": 0.91,
  "relevance_score": 0.94,
  "reason_code": "EXPLICIT_PROPOSITION"
}
```

标签：

- `direct`：段落明确表达可支持该观点的命题。
- `indirect`：段落相关，但需要进一步推论。
- `counter`：段落对观点提出否定、限制或相反材料。
- `context_only`：提供背景，不直接支撑。
- `irrelevant`：不相关，最终过滤。

模型或重排器不能把自身解释写入正式引文。

### 7.6 排序

默认标签优先级：`direct > indirect > context_only`。`counter` 作为独立分组展示，不与支持材料混排。

组内排序键：

1. 支撑分。
2. 重排相关分。
3. RRF 分。
4. 向量相似度。

### 7.7 证据不足

- 无 direct/indirect：只显示相关或相反材料，并标记 `INSUFFICIENT_SUPPORT`。
- 只有一个弱间接证据：不得生成“该观点得到原著明确支持”的说明。
- 超出语料：返回范围说明，不用常识补答。

---

## 8. 管线三：时间序列检索

### 8.1 召回与相关性门

使用管线二的混合召回、融合和相关性重排，但支撑标签可改为 `directly_addresses / related / background / irrelevant`。

先应用相关性阈值，再排序时间。任何候选不能仅因日期明确而入选。

### 8.2 时间键

```text
primary_date = work_date_start
secondary_date = work_date_end
fallback_date = first_publication_date
```

规则：

- 优先写作时间。
- 只有写作时间完全未知时才用首次发表时间，并在结果显示“按首次发表时间定位”。
- 版本出版年不参与思想材料时间排序。
- `unknown` 和 `disputed` 单列。

### 8.3 日期区间排序

- 明确起始时间按起始时间升序。
- 同一起始时间按结束时间、卷次和著作顺序排序。
- `approximate` 可以进入相应时期，但显示“约”。
- `disputed` 不参与精确先后结论。

### 8.4 时间分组

V1 默认按年代或配置的自然时间窗口分组，不预设固定思想阶段。示例：

```json
{
  "group_id": "decade_1840",
  "label": "1840年代",
  "group_type": "calendar_bucket",
  "evidence_ids": ["ev_..."]
}
```

如未来使用“早年/中期/晚年”等研究分期，必须来源于版本化 taxonomy 配置并在界面说明。

### 8.5 阶段摘要

阶段摘要是可选功能。模型输入只含当前组 evidence 和用户问题，输出：

```json
{
  "summary": "...",
  "claims": [
    {"text": "...", "evidence_ids": ["ev_..."]}
  ]
}
```

EvidenceService 校验所有 ID。无合法 evidence 的 claim 删除；剩余 claim 为空时不显示摘要。

---

## 9. 管线四：思想结构检索

### 9.1 证据池

沿用混合召回、融合、去重和相关性门。只有最终相关证据进入聚类，避免无关候选影响主题中心。

### 9.2 聚类输入

- 每个 `evidence_id` 使用一个聚合向量。
- 多 retrieval units 可取与查询最相关单元的向量，或使用版本化聚合策略。
- 聚类前记录向量模型、归一化方式和距离度量。
- 少于 `min_cluster_input` 时不聚类，直接返回单组相关材料。

### 9.3 V1 聚类算法

推荐凝聚层次聚类作为基线：

1. 计算证据向量间距离。
2. 按配置 linkage 合并。
3. 依据距离阈值切分。
4. 小于最小簇大小的点进入 `other_related` 或与最近簇合并；选择规则必须固定。
5. 设置 `min_clusters / max_clusters`，超过边界时调整阈值并记录。

不应为了得到预设类别数量而无条件使用固定 K。

### 9.4 主题标签

模型只读取单簇证据，返回：

```json
{
  "cluster_id": "cluster_01",
  "label": "...",
  "summary": "...",
  "evidence_ids": ["ev_..."],
  "confidence": 0.0
}
```

约束：

- 标签简短，不使用引号伪装原文。
- 不生成证据池外的著作、页码或引文。
- label 为空或校验失败时使用确定性回退名“主题 1”。
- UI 显示“本次检索的语义组织，并非唯一权威分类”。

### 9.5 类间和类内排序

类间：簇内最高相关度、平均相关度和证据数的版本化组合。
类内：相关性分、支撑度、MMR 多样性。

每个 evidence 只能出现在一个主题组或 `other_related`。同文异版折叠不算重复归类。

---

## 10. EvidenceService

### 10.1 输入

- `Candidate[]` 或分组后的 evidence IDs。
- `ResolvedScope`。
- `data_version / index_version`。
- 管线模式和排序理由。

### 10.2 证据门顺序

1. ID 存在性。
2. `verification_status=verified`。
3. `release_status=published`。
4. corpus/edition/volume/work/author/content_type 范围复核。
5. `text_hash` 与向量索引一致性检查（使用向量候选时）。
6. 元数据和页面发布状态检查。
7. 模型引用 ID 必须属于本次候选池。

任一步失败：候选不进入结果，写入 `exclusion_reason`。证据不足阈值在过滤后计算。

### 10.3 回填

EvidenceService 批量查询，禁止每个 ID 单独查询造成 N+1：

- `passage.verified_text`
- 作者、著作、版本和卷次
- 写作/发表时间及精度
- 印刷页和 PDF 页
- 相邻 evidence IDs
- content type
- 当前修订号

LanceDB 的 `search_text` 不能覆盖 SQLite `verified_text`。

### 10.4 上下文

- 默认只返回相邻 ID，不默认加载全部相邻正文。
- 用户展开时调用 context endpoint。
- 上下文不能跨著作。
- 非 published 相邻段不展示。
- 前端明确区分当前命中段和上下文段。

### 10.5 引用格式

引用显示数据由结构化字段生成，例如：

```text
马克思：《著作名》，《马克思恩格斯文集》第1卷，人民出版社2009年版，第X页。
```

引用模板可以配置，但字段值不能由模型生成。

---

## 11. 分页与 Top K

### 11.1 候选预算

初始建议值只作为配置起点：

```yaml
retrieval:
  lexical_top_k: 100
  vector_top_k: 100
  fusion_top_k: 80
  rerank_top_k: 50
  final_top_k: 20
  rrf_k: 60
```

正式值由评测确定。配置哈希写入审计。

### 11.2 分页一致性

- 请求绑定 data/index version。
- 深分页优先使用游标，游标包含排序键和版本，不只包含页号。
- index version 改变后旧游标返回 `STALE_CURSOR`，不混合两版结果。
- thematic/timeline 按组分页时必须保持组边界，响应说明分页语义。

---

## 12. 超时与降级

| 故障 | 允许的降级 | 禁止行为 |
|---|---|---|
| LanceDB 不可用 | exact 仍可运行；其他管线可在产品允许时返回仅关键词候选并明确警告 | 静默声称完成语义检索 |
| Reranker 超时 | 返回融合排序并标记 `RERANKER_UNAVAILABLE` | 伪造重排分 |
| LLM 超时 | 返回证据，不显示阶段摘要或主题语义标签 | 阻断原文证据展示 |
| SQLite 不可用 | 请求失败 | 用 LanceDB `search_text` 代替正式引文 |
| 索引版本不匹配 | 拒绝查询或切到完整的上一发布组合 | 混用新数据与旧索引 |

任何降级必须进入 `warnings` 和审计日志。

---

## 13. 审计事件

每次查询至少记录：

- 原查询、用户选择模式和路由建议。
- 解析后的范围快照。
- data/index/model/config 版本。
- 各通道候选 ID、名次和得分。
- 融合、去重、重排、聚类和过滤结果。
- Evidence Gate 排除原因。
- 最终 evidence IDs 和分组。
- 各阶段耗时和降级警告。

生产日志中是否保存完整查询文本由隐私策略决定；评测环境必须可完整复现。

---

## 14. 管线测试

### 14.1 契约测试

每个存储和模型适配器使用相同 fixture 验证：

- Scope 过滤语义一致。
- Candidate 字段和值域一致。
- 排序稳定。
- 错误被转换为统一错误码。
- 超时和取消能够传播。

### 14.2 关键不变量

- exact 最终结果 100% 包含原查询字符串。
- 所有最终 evidence 均属于 scope。
- 所有正式引文来自 SQLite。
- timeline 先过相关性门再按时间排序。
- thematic 每个 evidence 最多属于一个主题。
- 模型返回证据池外 ID 时不得进入结果。
- 检索依赖失败时不得静默改变管线含义。

---

## 15. 验收标准

| 模块 | 放行条件 |
|---|---|
| Exact | 精确率 100%，短词题集无已知漏检，无语义候选混入 |
| Claim | Top10 召回达到基线，不把明显反例标为直接支撑 |
| Timeline | 已知日期排序 100% 正确，未知/争议日期不伪造 |
| Thematic | 证据不重复归类，离群项处理稳定，标签均可回溯到簇内证据 |
| EvidenceService | 范围外、未发布、哈希不一致、模型越权 ID 全部阻断 |
| Audit | 任一评测查询可重放候选、版本、配置和结果 |
