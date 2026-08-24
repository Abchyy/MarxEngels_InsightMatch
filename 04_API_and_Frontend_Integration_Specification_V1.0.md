# API 与前端集成技术规范

**Document ID:** INTEGRATION-SPEC-04
**Version:** V1.0
**Parent document:** `Marx_Engels_Text_Retrieval_Assistant_Technical_Design_V1.1.md`
**Dependency:** `03_Retrieval_Pipelines_and_Evidence_Service_Specification_V1.0.md`

---

## 1. 目标

本文冻结 V1 前后端之间的 HTTP API、请求响应 Schema、错误码、页面状态和四种结果视图，使前端可使用 mock 数据独立开发，后端可使用契约测试独立实现。

技术基线：

- 后端：FastAPI + Pydantic。
- 前端：React + TypeScript + Vite。
- API 前缀：`/api/v1`。
- 数据格式：UTF-8 JSON。
- OpenAPI：由 FastAPI 路由和 Pydantic 模型生成，作为契约源。

---

## 2. API 设计原则

1. API 对外使用稳定领域对象，不泄露 SQLite 或 LanceDB 内部对象。
2. 所有成功响应带 `request_id`、数据版本和必要警告。
3. 所有错误使用统一 `ErrorResponse`，不把 Python 堆栈返回前端。
4. Pydantic 模型同时用于输入校验、响应过滤和 OpenAPI Schema。
5. `mode` 由用户最终选择；后端只提供模式建议。
6. 正式 Evidence 只来自 EvidenceService。
7. V1 先使用普通请求/响应；只有压测证明必要时才增加流式协议。

---

## 3. 路由清单

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/health/live` | 进程存活检查 |
| `GET` | `/api/v1/health/ready` | SQLite、发布版本和必要依赖就绪检查 |
| `GET` | `/api/v1/corpora` | 获取已发布语料集合 |
| `GET` | `/api/v1/corpora/{corpus_id}/scope-tree` | 获取版本、卷、著作和作者筛选树 |
| `POST` | `/api/v1/query-mode/suggest` | 建议检索方式 |
| `POST` | `/api/v1/search` | 执行四种检索之一 |
| `GET` | `/api/v1/evidence/{evidence_id}` | 获取单条证据 |
| `GET` | `/api/v1/evidence/{evidence_id}/context` | 获取前后语境 |
| `GET` | `/api/v1/evidence/{evidence_id}/pdf-location` | 获取 PDF 定位信息 |
| `POST` | `/api/v1/feedback` | 提交语料或结果问题 |
| `GET` | `/api/v1/meta/release` | 获取当前数据和索引版本 |

后台语料管理 API 不纳入公开 `/api/v1`；应使用独立路由、权限和文档。

---

## 4. 公共模型

### 4.1 Scope

```json
{
  "corpus_ids": ["marx_engels_collected_works_cn"],
  "edition_ids": ["people_press_2009_cn"],
  "volume_ids": [],
  "work_ids": [],
  "authors": [],
  "content_types": ["main_text", "author_note"]
}
```

语义：空的下级数组表示当前上级范围内全部已发布对象。`corpus_ids` 不得为空。

### 4.2 ReleaseInfo

```json
{
  "data_version": "data_2026_08_24_001",
  "index_version": "idx_2026_08_24_001",
  "embedding_model": "provider/model@version",
  "released_at": "2026-08-24T12:00:00+08:00"
}
```

exact 模式可以不使用向量索引，但响应仍返回当前 `data_version`；`index_version` 可以为空。

### 4.3 Warning

```json
{
  "code": "RERANKER_UNAVAILABLE",
  "message": "重排服务暂不可用，本次结果使用融合排序。",
  "stage": "rerank"
}
```

---

## 5. 语料范围 API

### 5.1 获取语料集合

```http
GET /api/v1/corpora
```

```json
{
  "items": [
    {
      "corpus_id": "marx_engels_collected_works_cn",
      "display_name": "马克思恩格斯文集",
      "language": "zh-CN",
      "release_status": "published"
    }
  ]
}
```

### 5.2 获取范围树

```http
GET /api/v1/corpora/marx_engels_collected_works_cn/scope-tree
```

响应包括 editions、volumes、works、authors 和各节点是否已发布。前端不得自行写死十卷列表。

范围树应支持 ETag 或版本字段；语料版本变化后前端刷新缓存。

---

## 6. 模式建议 API

### 6.1 请求

```http
POST /api/v1/query-mode/suggest
Content-Type: application/json
```

```json
{
  "query": "马克思恩格斯如何看待舆论"
}
```

### 6.2 响应

```json
{
  "suggested_mode": null,
  "confidence": 0.91,
  "requires_user_selection": true,
  "allowed_modes": ["timeline", "thematic"],
  "reason_code": "QUESTION_OR_DOMAIN"
}
```

当前端收到 `requires_user_selection=true`，必须展示“按时间呈现/按思想结构呈现”，不能默认选择其一后立即检索。

---

## 7. 搜索 API

### 7.1 请求

```http
POST /api/v1/search
Content-Type: application/json
```

```json
{
  "query": "马克思恩格斯如何看待舆论",
  "mode": "timeline",
  "scope": {
    "corpus_ids": ["marx_engels_collected_works_cn"],
    "edition_ids": ["people_press_2009_cn"],
    "volume_ids": [],
    "work_ids": [],
    "authors": [],
    "content_types": ["main_text", "author_note"]
  },
  "sort": null,
  "cursor": null,
  "page_size": 20,
  "options": {
    "include_generated_summaries": true,
    "include_counter_evidence": true
  }
}
```

### 7.2 成功响应

```json
{
  "request_id": "req_...",
  "mode": "timeline",
  "query": "马克思恩格斯如何看待舆论",
  "scope_snapshot": {},
  "release": {
    "data_version": "data_...",
    "index_version": "idx_..."
  },
  "overview": {
    "evidence_count": 18,
    "work_count": 7,
    "volume_count": 4,
    "result_note": "以下组织只基于列出的证据。"
  },
  "groups": [],
  "evidence": [],
  "next_cursor": null,
  "insufficiency": null,
  "warnings": []
}
```

### 7.3 各模式响应约束

#### `exact`

- `groups` 可为空。
- `evidence` 为平铺列表。
- Evidence 带 `exact_match_count` 和命中位置。
- 不返回机器归纳。

#### `claim`

- `groups` 建议为 `supporting / counter / contextual`。
- 每条 Evidence 带 `support_label`。
- 支持材料不足时返回 `insufficiency`。

#### `timeline`

- `groups` 按时间升序。
- 每组有 `date_start / date_end / date_precision / group_type`。
- 时间未知或争议组始终位于已知时间组之后。

#### `thematic`

- `groups` 为主题簇。
- 每组有 `label / summary / evidence_ids / confidence`。
- 响应必须包含 `classification_notice`。

### 7.4 Evidence 响应

```json
{
  "evidence_id": "ev_...",
  "verified_text": "……",
  "content_type": "main_text",
  "author": "马克思",
  "work_title": "……",
  "corpus_name": "马克思恩格斯文集",
  "edition_label": "人民出版社2009年版",
  "volume_no": 1,
  "work_date_start": "1845",
  "work_date_end": "1845",
  "date_precision": "year",
  "printed_pages": ["123"],
  "pdf_pages": [145],
  "prev_evidence_id": "ev_prev",
  "next_evidence_id": "ev_next",
  "match_type": "semantic",
  "support_label": "direct",
  "rank_reasons": ["直接回应观点", "语义相关度高"]
}
```

---

## 8. 证据与上下文 API

### 8.1 单条证据

```http
GET /api/v1/evidence/{evidence_id}
```

只返回当前已发布版本中的证据。已撤回或 superseded 的 ID 返回 `EVIDENCE_NOT_AVAILABLE`，可在授权后台提供修订链。

### 8.2 上下文

```http
GET /api/v1/evidence/{evidence_id}/context?before=1&after=1
```

约束：

- `before/after` 各自限制在 0—3。
- 不跨著作。
- 返回 `target_evidence_id` 和按顺序排列的 context items。
- 当前命中段带 `is_target=true`。
- 未发布段不得作为上下文泄露。

### 8.3 PDF 定位

```http
GET /api/v1/evidence/{evidence_id}/pdf-location
```

```json
{
  "evidence_id": "ev_...",
  "asset_id": "asset_...",
  "viewer_url": "/api/v1/assets/asset_...?token=short_lived",
  "start_pdf_page": 145,
  "end_pdf_page": 146,
  "printed_pages": ["123", "124"],
  "coordinates": null
}
```

资产访问令牌、授权和缓存策略由部署配置实现。禁止向前端暴露服务器真实文件路径。

---

## 9. 反馈 API

### 9.1 请求

```json
{
  "request_id": "req_...",
  "evidence_id": "ev_...",
  "category": "page_mismatch",
  "comment": "正文页码可能不正确",
  "client_context": {
    "route": "/search",
    "data_version": "data_..."
  }
}
```

合法 category：

- `ocr_error`
- `page_mismatch`
- `work_metadata_error`
- `author_error`
- `context_boundary_error`
- `irrelevant_result`
- `other`

反馈只创建待办，不直接修改 Verified 数据。

---

## 10. 错误协议

### 10.1 统一格式

```json
{
  "request_id": "req_...",
  "error": {
    "code": "INVALID_SCOPE",
    "message": "所选著作不属于当前卷次。",
    "details": {},
    "retryable": false
  }
}
```

### 10.2 主要错误码

| HTTP | Code | 场景 |
|---|---|---|
| 400 | `INVALID_REQUEST` | JSON 或字段语义错误 |
| 400 | `MODE_SELECTION_REQUIRED` | 问题/领域尚未选择 timeline/thematic |
| 400 | `INVALID_SCOPE` | 范围层级冲突 |
| 404 | `CORPUS_NOT_FOUND` | 语料不存在或未发布 |
| 404 | `EVIDENCE_NOT_AVAILABLE` | 证据不存在、已撤回或无权限 |
| 409 | `STALE_CURSOR` | 游标版本与当前发布不一致 |
| 409 | `RELEASE_MISMATCH` | 数据与索引版本组合无效 |
| 422 | `QUERY_TOO_LONG` | 查询超过限制 |
| 429 | `RATE_LIMITED` | 超过限流 |
| 503 | `SQLITE_UNAVAILABLE` | 真源不可用，不能返回正式证据 |
| 503 | `VECTOR_INDEX_UNAVAILABLE` | 语义索引不可用且不能安全降级 |
| 504 | `SEARCH_TIMEOUT` | 查询总超时 |

FastAPI 全局异常处理器负责把领域异常映射为此格式。

---

## 11. FastAPI 实现约束

### 11.1 路由组织

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def search(request: SearchRequest) -> SearchResponse:
    return await search_service.execute(request)
```

要求：

- 每个路由声明 `response_model`。
- OpenAPI `operation_id` 稳定，供 TypeScript 客户端生成。
- 领域服务不抛出带 HTTP 语义的异常；HTTP 映射只在 API 层。
- 阻塞型 SQLite/LanceDB/模型调用不得直接阻塞事件循环；实现方式由适配器确定并测试。
- 请求取消时向下游传播，避免用户离开后继续消耗模型资源。

### 11.2 OpenAPI 契约

- CI 导出 `openapi.json`。
- 前端 TypeScript 类型和客户端从固定 OpenAPI 生成或与其做差异检查。
- 删除字段、改变类型或错误语义属于破坏性变更。
- 新增可选字段必须保持旧客户端可用。

---

## 12. 前端信息架构

### 12.1 页面

```text
SearchPage
├── CorpusScopePanel
├── QueryComposer
│   ├── QueryInput
│   ├── ModeSelector
│   └── SearchOptions
├── SearchOverview
├── ResultRegion
│   ├── ExactResultList
│   ├── ClaimResultGroups
│   ├── TimelineView
│   └── ThematicGroups
├── EvidenceContextDrawer
└── PdfViewerPanel
```

### 12.2 查询输入状态

```text
idle
→ suggesting_mode
→ awaiting_mode_selection | ready
→ searching
→ success | empty | partial | error
```

- `awaiting_mode_selection` 时不发送 search 请求。
- 新查询发出后取消上一未完成请求。
- scope 改变时旧结果标记为过期，用户确认后重新查询。
- URL 可保存 query、mode 和非敏感 scope，便于复现；不保存临时资产令牌。

### 12.3 结果公共区域

每次结果顶部显示：

- 原查询。
- 检索模式。
- 实际范围。
- 证据、著作和卷次数量。
- 数据版本和必要警告。
- “以下组织只基于列出的证据”。

### 12.4 EvidenceCard

```text
[命中/支撑标签] [排序原因]
原文 verified_text
作者｜著作｜版本｜卷次｜正文页
[展开语境] [在 PDF 中查看] [反馈问题]
```

禁止行为：

- 将机器摘要放在与原文相同的引号样式中。
- 用 LanceDB `search_text` 作为卡片原文。
- 隐藏“相反材料”标签。
- 只显示 PDF 页而不显示印刷页。

---

## 13. 四种结果视图

### 13.1 ExactResultList

- 高亮所有逐字命中位置。
- 展示命中次数。
- 默认按相关排序，可切换卷页顺序。
- 无结果时提供“改用语义检索”按钮，但不自动发起。

### 13.2 ClaimResultGroups

- 直接支撑、间接相关、相反材料分别分组。
- 默认展开直接支撑。
- 支撑不足提示位于结果首屏。
- 相反材料不应因与用户观点不一致而隐藏。

### 13.3 TimelineView

- 时间从上到下或从左到右一致呈现。
- 日期区间、约数、争议和未知使用不同文本标识，不能只依赖颜色。
- 同一著作多段可折叠。
- 阶段摘要标记“机器归纳”，支持关闭。

### 13.4 ThematicGroups

- 主题组显示标签、说明和 evidence 数量。
- 页面固定显示“语义聚类不是唯一权威思想分类”。
- 支持关闭机器标签后显示“主题 1、主题 2”。
- `other_related` 不隐藏。
- 同一 evidence 不在多个主题中重复出现。

---

## 14. 加载、空结果与降级

| 状态 | 前端行为 |
|---|---|
| Loading | 保留查询和范围，显示阶段性通用加载状态，不伪造结果骨架内容 |
| Empty exact | 明确“无逐字命中”，提供用户主动切换模式 |
| Insufficient claim | 显示已找到材料和不能证明的部分 |
| Partial | 展示可用证据，并在首屏显示后端 warnings |
| SQLite unavailable | 不展示缓存引文，显示正式证据暂不可用 |
| LLM unavailable | 继续展示证据，隐藏摘要/主题标签或显示确定性回退名 |
| Stale cursor | 提示结果版本已更新，从第一页重新查询 |

---

## 15. 可访问性与安全

- 所有模式、日期精度和支撑关系不能只用颜色表达。
- 键盘可以完成查询、筛选、展开证据和打开 PDF。
- 原文与机器摘要具有明确的语义标签。
- 高亮使用 `<mark>` 等语义元素，不修改复制出的原文。
- 渲染文本时默认转义 HTML，禁止直接插入未经处理的模型输出。
- PDF 资产 URL 使用受控接口，不暴露真实磁盘路径。
- 反馈内容按不可信输入处理。

---

## 16. 前后端契约测试

至少覆盖：

- 四种 mode 的成功 fixture。
- `MODE_SELECTION_REQUIRED`。
- 非法 scope。
- exact 空结果。
- claim 支撑不足和相反材料。
- timeline 未知/争议日期。
- thematic 离群组与无模型标签降级。
- context 不跨著作。
- PDF 跨页定位。
- warnings 和错误码渲染。
- OpenAPI 破坏性变更检测。

---

## 17. 验收标准

| 项目 | 标准 |
|---|---|
| API | OpenAPI 可生成客户端，示例请求响应通过 Schema 校验 |
| 模式 | 问题/领域未经用户选择不会执行 timeline/thematic |
| Evidence | 前端展示字段全部来自 Evidence 响应 |
| 四视图 | exact、claim、timeline、thematic 有独立且正确的结果结构 |
| 空/降级 | 不把无结果、证据不足或服务降级包装成完整答案 |
| PDF | 任一证据可打开正确 PDF 页，不暴露服务器路径 |
| 兼容性 | API 可选字段增加不破坏现有前端，破坏性变更被 CI 阻断 |
