# 测试、部署与运维技术规范

**Document ID:** DELIVERY-SPEC-05
**Version:** V1.0
**Parent document:** `Marx_Engels_Text_Retrieval_Assistant_Technical_Design_V1.1.md`
**Dependencies:** Documents 01—04

---

## 1. 目标

本文规定测试分层、四管线评测、持续集成、环境配置、部署、备份、索引发布、监控、回滚和故障处理。目标是让任何发布版本都能够回答：使用了哪一版语料、哪一版索引、哪些模型、为什么返回这些证据，以及如何安全回退。

---

## 2. 环境

| 环境 | 用途 | 数据要求 |
|---|---|---|
| `local` | 单人开发 | 合成或脱敏小样本，不共享生产文件 |
| `test` | 自动测试 | 固定 fixture 和 golden dataset |
| `staging` | 集成、压测、发布演练 | 与生产结构一致的授权测试语料 |
| `production` | 正式服务 | 已校验、已授权、已发布的十卷语料 |

禁止开发和自动测试直接写生产 SQLite、LanceDB 或 PDF 目录。

---

## 3. 标准开发命令

项目应为合作者提供稳定、英文命名的命令入口。底层实现可以变化，但这些入口保持兼容：

```text
make setup
make lint
make typecheck
make test
make test-unit
make test-integration
make test-contract
make test-regression
make migrate
make verify-corpus
make build-index
make verify-index
make run-api
make run-web
make export-openapi
make backup
make restore-check
```

要求：

- 命令在项目根目录执行。
- 每个命令非零退出表示失败。
- 命令不得隐式访问生产环境。
- 破坏性命令必须显式要求环境和目标版本，不能使用模糊默认路径。
- README 只说明入口，详细规则以本文为准。

---

## 4. 测试分层

### 4.1 Unit Tests

覆盖纯逻辑：

- ID 和哈希生成。
- 文本清洗规则。
- 日期精度和时间排序。
- RRF、去重、MMR 和聚类辅助逻辑。
- 错误码映射。
- 引用格式化。
- Evidence Gate 单项规则。

单元测试不得依赖真实网络模型。

### 4.2 Contract Tests

覆盖模块之间的稳定接口：

- SQLite repository 实现满足 `MetadataRepository`。
- LanceDB adapter 满足 `VectorIndex`。
- Embedding/Reranker/LLM adapter 的超时和错误语义一致。
- FastAPI OpenAPI 与前端生成类型一致。
- EvidenceService 只返回规定字段。

每个替代实现必须通过同一套契约测试。

### 4.3 Integration Tests

使用临时 SQLite、临时 LanceDB 和固定小型 PDF/语料 fixture，覆盖：

- 导入 → 校验 → 发布 → FTS/向量索引。
- 四管线召回 → Evidence Gate → API 响应。
- 跨页证据 → PDF 定位。
- outbox 失败、重试和幂等。
- 索引版本发布和回滚。
- SQLite 恢复后 LanceDB 重建。

### 4.4 End-to-End Tests

浏览器端覆盖：

- 词语输入和精确高亮。
- 观点检索的支撑/相反分组。
- 问题输入后必须选择时间或思想结构。
- 时间轴顺序和未知日期组。
- 思想主题分组与“仅看证据”。
- 上下文抽屉和 PDF 页跳转。
- 空结果、证据不足、降级和错误提示。
- 用户反馈创建待办但不修改原文。

---

## 5. Golden Dataset

### 5.1 目录

```text
tests/
  golden/
    corpus_fixture/
    exact_cases.jsonl
    claim_cases.jsonl
    timeline_cases.jsonl
    thematic_cases.jsonl
    evidence_gate_cases.jsonl
```

### 5.2 公共字段

```json
{
  "case_id": "claim_001",
  "query": "...",
  "mode": "claim",
  "scope": {},
  "expected_evidence_ids": ["ev_..."],
  "forbidden_evidence_ids": ["ev_..."],
  "expected_labels": {},
  "notes": "由研究者标注",
  "annotator": "...",
  "reviewer": "...",
  "dataset_version": "golden_v1"
}
```

### 5.3 标注规则

- 每个案例至少由一名标注者和一名复核者确认。
- 不只使用模型生成题目；至少一半来自真实研究任务。
- “应找到”必须落到具体 evidence ID，不只写模糊答案。
- 有争议案例单独标记，不进入强制自动门槛或采用宽松评价。
- 语料修订导致 ID superseded 时同步更新题集并保留变更记录。

---

## 6. 四管线评测

### 6.1 Exact

指标：

- Precision：返回段落是否逐字包含查询。
- Recall：标注范围内所有包含查询的段落是否召回。
- Scope Accuracy：是否全部属于范围。
- Ordering Stability：相同版本和配置下排序是否稳定。

放行：Precision 100%，Scope Accuracy 100%，golden cases 无已知漏检。

### 6.2 Claim

指标：

- Recall@10。
- MRR 或 nDCG。
- direct/indirect/counter 标签准确率。
- 明显反例误标为 direct 的数量。
- 证据不足正确降级率。

放行基线：人工题集 Recall@10 ≥ 85%，明显反例不得标为 direct，虚构引文为 0。

### 6.3 Timeline

指标：

- 入选证据相关率。
- 已知日期排序正确率。
- 日期精度显示正确率。
- unknown/disputed 处理正确率。
- 阶段摘要 evidence 绑定率。

放行：已知日期排序 100% 正确，日期不确定性无伪造，摘要 claim 的 evidence 绑定率 100%。

### 6.4 Thematic

指标：

- 证据覆盖率。
- 重复归类率。
- 类内语义一致性人工评分。
- 离群材料处理正确率。
- 标签与簇内证据一致率。

放行：每条 evidence 只出现一次或进入明确折叠关系；证据池外 ID 为 0；模型标签均可由簇内证据解释。

---

## 7. 不可妥协的发布门

以下任一失败均阻断发布：

- 正式引文与 SQLite `verified_text` 不一致。
- 作者、著作、版本、卷次或页码由模型生成。
- scope 外 evidence 进入结果。
- 未校验或未发布 passage 进入结果。
- LanceDB 孤儿 ID 进入结果。
- exact 返回不含原查询的段落。
- timeline 使用版本出版年冒充写作时间。
- thematic 把同一 evidence 无说明地放入多个主题。
- SQLite 备份无法恢复。
- 新索引无法回退到上一发布版本。

---

## 8. 持续集成

每个合并请求运行：

1. Markdown/配置格式检查。
2. Python/TypeScript lint。
3. 类型检查。
4. 单元测试。
5. 契约测试。
6. 临时双库集成测试。
7. OpenAPI 差异检测。
8. 小型检索回归题集。
9. 依赖和机密扫描。

主分支或发布候选额外运行：

- 完整 golden dataset。
- 语料完整性检查。
- 索引一致性检查。
- 性能基线。
- 备份恢复演练。
- PDF 定位抽检报告。

模型结果可能存在非确定性时，应固定模型版本、温度和结构化输出配置；仍不稳定的指标采用多次运行统计，不把偶然一次通过视为放行。

---

## 9. 版本策略

每次在线发布绑定：

```json
{
  "app_version": "1.0.0",
  "schema_version": 1,
  "data_version": "data_...",
  "index_version": "idx_...",
  "golden_dataset_version": "golden_v1",
  "pipeline_config_version": "pipeline_v1",
  "model_versions": {
    "embedding": "...",
    "reranker": "...",
    "llm": "..."
  }
}
```

禁止只记录“当前最新版”。日志、响应和发布报告必须能够还原具体组合。

---

## 10. 部署流程

### 10.1 部署前

- 代码和依赖锁文件已冻结。
- Schema migration 在 staging 演练。
- SQLite 已创建可恢复备份。
- 新数据和索引版本均通过检查。
- API、前端和 PDF 资产权限配置通过验证。
- 回滚目标版本仍可用。

### 10.2 推荐顺序

1. 停止语料写入任务或进入维护写模式。
2. 备份 SQLite 并验证备份元数据。
3. 执行 schema migration。
4. 部署后端，但继续指向旧发布组合。
5. 部署前端并运行 smoke tests。
6. 激活新的 `data_version + index_version`。
7. 运行四管线 smoke tests 和 PDF 定位测试。
8. 观察错误率、延迟和证据门告警。
9. 结束维护写模式。

### 10.3 回滚

- 应用错误：回滚 app version，保持兼容的数据/索引版本。
- 新索引质量下降：切回上一 `index_version`。
- 数据发布错误：切回上一完整的 `data_version + index_version` 组合。
- Schema 不向后兼容：使用发布前备份和经过演练的恢复步骤；不得临时运行破坏性 SQL。

回滚后记录事故、影响请求范围和后续修复动作。

---

## 11. 健康检查

### 11.1 Liveness

只确认 API 进程能够处理请求，不检查远程模型或大查询。

### 11.2 Readiness

检查：

- SQLite 可读。
- `foreign_keys` 已启用。
- active data version 为 published。
- 需要语义检索时 active index version 存在且为 published。
- PDF 资产根目录可读。
- Schema version 与应用兼容。

外部模型短时不可用是否导致整体 not ready，应按降级策略配置；SQLite 不可用必须 not ready。

---

## 12. 监控指标

### 12.1 请求

- 请求量、错误率、P50/P95/P99 延迟。
- 按 mode 分解的耗时。
- 取消、超时和限流数量。

### 12.2 检索

- SQLite exact/FTS 查询耗时。
- LanceDB 查询耗时。
- 各通道候选数、融合后候选数和最终证据数。
- Reranker/LLM 延迟、失败和降级率。
- `NO_EXACT_MATCH`、`INSUFFICIENT_SUPPORT` 比例。

### 12.3 数据质量

- Evidence Gate 各排除原因数量。
- 哈希不一致和孤儿 ID 数。
- 待处理 outbox 数量和最老事件年龄。
- 用户反馈数量、类型和处理时长。
- 当前 data/index version。

### 12.4 存储

- SQLite 文件、WAL 文件大小和锁等待。
- 备份成功、大小、校验和及最近恢复演练时间。
- LanceDB 目录大小和索引构建耗时。
- PDF 资产缺失或哈希异常。

---

## 13. 日志与追踪

所有模块使用同一个 `request_id`。结构化日志至少包含：

```json
{
  "timestamp": "...",
  "level": "INFO",
  "request_id": "req_...",
  "component": "claim_pipeline",
  "event": "rerank_completed",
  "duration_ms": 120,
  "data_version": "data_...",
  "index_version": "idx_...",
  "candidate_count": 50
}
```

禁止记录：

- 模型 API Key、资产访问令牌和密码。
- 未经策略允许的完整用户身份信息。
- 无必要的完整 PDF 内容。
- Python 堆栈直接返回用户。

查询原文是否长期保留必须由隐私策略明确；可使用 query hash 进行聚合统计。

---

## 14. 备份与恢复

### 14.1 备份对象

- SQLite 数据库。
- 语料 manifest 和发布清单。
- 原始 PDF 和资产清单。
- 当前及上一 LanceDB 发布版本，或可靠的重建材料。
- 应用配置的非机密版本化部分。

### 14.2 恢复顺序

1. 恢复资产清单和 PDF。
2. 使用 SQLite backup 恢复真源。
3. 执行完整性、外键和版本检查。
4. 验证 passage 到 PDF 页定位。
5. 恢复 LanceDB 或从 SQLite 重建。
6. 验证双库一致性。
7. 在 staging 执行四管线 smoke tests。
8. 恢复流量。

恢复目标时间和允许数据损失量应在首次生产部署前由项目负责人确定。

---

## 15. 故障处理手册

### 15.1 SQLite 锁等待上升

检查长事务、导入任务和写者数量；暂停非必要写任务。不得通过关闭外键或直接删除 WAL 文件处理。

### 15.2 LanceDB 与 SQLite 哈希不一致

停止使用受影响 index version，切回上一发布组合；定位 outbox 和构建批次，重建后重新验收。

### 15.3 模型服务不可用

exact 不受影响。其余管线按规范降级；证据可用时优先展示证据，不生成摘要。不得用旧模型输出冒充本次结果。

### 15.4 PDF 无法打开

保留证据文本和出处，显示 PDF 暂不可用警告；检查资产记录、访问权限和哈希。错误页码反馈进入校验队列。

### 15.5 发现错误正式引文

按 P0 数据质量事故处理：撤回相关数据版本或证据、保留审计、修订并复校、重建索引、重新发布，并检查受影响查询。

---

## 16. 发布检查表

- [ ] Unit、contract、integration、E2E 测试通过。
- [ ] 四管线 golden dataset 达标。
- [ ] 引文、范围和模型越权测试通过。
- [ ] 十卷语料发布清单完整。
- [ ] SQLite integrity/foreign key 检查通过。
- [ ] LanceDB 数量、哈希、维度和孤儿 ID 检查通过。
- [ ] OpenAPI 与前端客户端一致。
- [ ] PDF 定位抽检通过。
- [ ] 备份已生成并完成恢复验证。
- [ ] 上一发布组合仍可回滚。
- [ ] 监控、告警和日志可见。
- [ ] 发布负责人和回滚负责人明确。

---

## 17. 验收标准

| 项目 | 标准 |
|---|---|
| 自动化 | 关键模块具有单元、契约和集成测试 |
| 质量门 | 任一红线失败自动阻断发布 |
| 复现 | 可用版本组合复现评测查询 |
| 部署 | staging 完成迁移、切换和回滚演练 |
| 备份 | SQLite 恢复成功，向量索引可重建 |
| 运维 | 核心请求、数据质量、双库一致性和 outbox 均可监控 |
| 协作 | 英文标准命令和发布检查表可由不同合作者重复执行 |
