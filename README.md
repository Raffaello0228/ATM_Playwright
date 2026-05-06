# ATM-Playwright

AI Agent 自动化测试框架。以 Claude 作为测试驱动引擎，通过 `playwright-cli` 操控真实浏览器，结合 Langfuse trace 观测，完成 Agent 的端到端验收测试。

---

## 快速上手

### 1. 安装依赖

```bash
git clone <this-repo>
cd ATM-Playwright
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. 安装 playwright-cli

macOS：
```bash
brew install playwright-cli
```

Windows：
```powershell
npm install -g @playwright/cli
```

### 3. 配置凭证

```bash
cp agent-test.example.yaml agent-test.yaml
# 编辑 agent-test.yaml，填入 Langfuse 密钥和 Agent URL
```

```yaml
# agent-test.yaml
playwright:
  url: "https://your-agent-ui.example.com/chat"

langfuse:
  public_key: "pk-lf-..."
  secret_key: "sk-lf-..."
  base_url: "https://cloud.langfuse.com"
```

也可以用环境变量代替：`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`

### 4. 配置 atm-playwright skill

将 repo 中的 `skills/` 目录复制到 Claude Code 的 skill 目录：

macOS / Linux：
```bash
cp -r skills/ ~/.claude/skills/atm-playwright
```

Windows：
```powershell
Copy-Item -Recurse skills\ "$env:USERPROFILE\.claude\skills\atm-playwright"
```

复制后目录结构应为：
```
~/.claude/skills/atm-playwright/
├── SKILL.md
└── modes/
    ├── a-design.md
    ├── b-execute.md
    ├── c-evaluate.md
    └── d-verify.md
```

重启 Claude Code 后 skill 自动生效，在对话中说"执行测试 Mode B，用例 CASE_001"即可开始。

---

## 接入新项目

### 项目接入步骤

1. **新建项目目录**：`mkdir project/{your_project_name}`

2. **填写操作指南**：
   ```bash
   cp project/operation_guide.template.md project/{your_project_name}/operation_guide.md
   # 按模板说明填写：登录方式、session_id 提取、HITL 关键词、CSS selector 等
   ```

3. **编写评估标准**：创建 `project/{your_project_name}/evaluation_criteria.md`，定义各维度的评分规则

4. **设计测试用例**：创建 `project/{your_project_name}/cases.csv`，参考 `modes/a-design.md`（`expected_tools` 填写 Langfuse 上报的原始工具名）

### 操作指南编写方法

`operation_guide.md` 不靠猜测，靠「跑一遍发现」。推荐用 Claude Code 完成：

1. **写初稿**：复制 `project/operation_guide.template.md`，手动走一遍 Agent 完整流程，填写登录方式、session_id 提取规则、DONE 判断 selector、HITL 检测方式等占位项

2. **跑第一个用例**：让 Claude Code 执行 Mode B，过程中会遇到模板与实际不符的地方（如 DONE 检测时机、HITL 表单结构、输出格式等），Claude Code 会自行调试并找到可用的代码

3. **回填操作指南**：用例跑通后，让 Claude Code 将本次调试验证过的 selector 和代码片段更新回 `operation_guide.md`，替换模板占位符

**一次跑通 = 一次校准**，文档随项目迭代。参考样本：`project/素材策略/operation_guide.md`

### 运行测试

在 Claude Code 中启动对话，指定模式：
- `"执行 Mode B，用例 CASE_001，项目 {your_project_name}"`
- `"执行 Mode C 评估，test_run_id = CASE_001_20260501_100012"`

---

## 三个工作模式

### 模式 A — 设计测试用例

根据业务文档和评估标准，编写 CSV 用例。参见 `modes/a-design.md`。

用例字段：

| 字段 | 说明 |
|------|------|
| `case_id` | 唯一标识，如 `CASE_001` |
| `title` | 用例标题 |
| `description` | 场景描述（触发条件 → 预期分支） |
| `user_query` | 发给 Agent 的初始消息 |
| `final_intent` | 期望的对话走向（评估依据） |
| `max_turns` | 最多对话轮数 |
| `expected_tools` | 预期调用工具，` / ` 分隔，如 `联网搜索 / 报告生成` |
| `case_type` | 分类，如 `normal_flow`、`boundary` |
| `fixtures` | 附件相对路径，` / ` 分隔（可选） |
| `operation_guide` | 操作指南文件路径，相对 repo 根目录（可选） |

### 模式 B — 执行测试

Claude 驱动浏览器完成对话，记录每轮工具调用和响应。参见 `modes/b-execute.md`。

执行流程：
```
读用例（Read CSV）
→ 写 context.json
→ 打开浏览器（playwright-cli）
→ 发消息 → waitForFunction 等待完成/HITL
→ 查询 Langfuse（query_langfuse.py）
→ 累积 turns
→ 写出 turns.jsonl
```

### 模式 C — 评估打分

读取 turns.jsonl 和 evaluation_criteria.md，按维度打分，直接写出 result.json 和 report.md。参见 `modes/c-evaluate.md`。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│  Claude (LLM)                                           │
│  ├── playwright-cli  →  操控浏览器（发消息、检测状态）   │
│  ├── Read/Write 工具 →  直接读写文件（用例、报告、状态） │
│  └── query_langfuse.py CLI → 查询 Langfuse trace        │
├─────────────────────────────────────────────────────────┤
│  文件系统                                               │
│  ├── project/{name}/cases.csv  →  测试用例              │
│  ├── reports/{test_run_id}/    →  运行输出              │
│  └── reports/batches/          →  批次汇总              │
└─────────────────────────────────────────────────────────┘
```

**核心设计原则：**
- **无 MCP server**，所有状态存文件，进程重启不丢失
- Claude 用原生 Read/Write 工具管理用例和报告，操作透明可审查
- 唯一需要 Python 的操作是查询 Langfuse（HTTP 请求），由 `src/tools/query_langfuse.py` CLI 脚本承担
- 通过 Langfuse session_id 关联 trace，**零侵入**被测 Agent
- 测试用例为纯 CSV 文件，评估标准为 Markdown 文档，均可 Git 版本管理

---

## 目录结构

```
ATM-Playwright/
├── src/
│   ├── tools/
│   │   ├── query_langfuse.py      # Langfuse 查询 CLI（唯一需要 Python 的操作）
│   │   └── update_batch.py        # 批次摘要写入 CLI
│   └── adapters/
│       └── langfuse_client.py     # Langfuse REST API 客户端
├── modes/
│   ├── a-design.md                # 模式 A：设计测试用例
│   ├── b-execute.md               # 模式 B：执行测试
│   └── c-evaluate.md              # 模式 C：评估打分
├── project/
│   ├── operation_guide.template.md  # 操作指南模板（接入新项目时复制填写）
│   └── <project_name>/            # 业务套件目录
│       ├── cases.csv              # 测试用例（CSV 格式）
│       ├── operation_guide.md     # 浏览器操作说明
│       ├── evaluation_criteria.md # 评分标准
│       └── *.png / *.pdf          # 上传附件（fixtures）
├── reports/
│   ├── batches/                   # 批次汇总
│   │   └── {batch_id}.json
│   └── <test_run_id>/             # 每次测试的输出
│       ├── context.json           # session 元信息（playwright_url、langfuse_session_id 等，Mode B 开始时写入）
│       ├── turns.jsonl            # 对话记录（JSONL，Mode B 结束时写入）
│       ├── result.json            # 评估结果
│       └── report.md              # Markdown 报告
├── agent-test.yaml                # 本地配置（不提交 Git）
└── agent-test.example.yaml        # 配置模板
```

---

## CLI 工具

### `query_langfuse.py`

查询 Langfuse session 的所有 trace：

```bash
.venv/bin/python src/tools/query_langfuse.py \
  --session-id <langfuse_session_id> \
  [--min-timestamp <ISO-8601>] \
  [--limit 50]
```

输出（stdout JSON）：
```json
{
  "ok": true,
  "found": true,
  "traces_count": 3,
  "tool_calls": ["联网搜索", "报告生成"],
  "tool_calls_raw": ["web_search", "generate_report"],
  "latency_ms": 45000,
  "input_tokens": 12000,
  "output_tokens": 800,
  "traces": [...]
}
```

`found: false` 时表示 trace 尚未同步，等待 3-5 秒后重试。

### `update_batch.py`

将单次测试结果追加到批次汇总文件：

```bash
.venv/bin/python src/tools/update_batch.py \
  --batch-id <batch_id> \
  --test-run-id <test_run_id> \
  [--project-name <project_name>] \
  [--agent-version <version>]
```

`batch_id` 建议格式：`{project_name}_{yyyymmdd_HHMMSS}` 或自定义标签（如 `v1.2-hotfix`）。

批次文件路径：`reports/batches/{batch_id}.json`，结构：

```json
{
  "batch_id": "市场洞察_20260501_100000",
  "runs": [
    {"test_run_id": "...", "case_id": "CASE_001", "passed": true, "score": 8.5}
  ],
  "summary": {
    "total": 5, "passed": 4, "failed": 1,
    "pass_rate": 0.8, "avg_score": 7.9
  }
}
```

---

## 报告格式

### context.json

```json
{
  "test_run_id": "CASE_001_20260501_100012",
  "playwright_url": "https://...",
  "langfuse_session_id": "ecbr-rec-3791",
  "agent_name": "Marvy Agent",
  "started_at": "2026-05-01T10:00:12Z",
  "fixtures_abs": ["/abs/path/to/project/suite/image.png"]
}
```

### turns.jsonl

第一行为 `_meta`，后续每行一条对话记录（原名 `context.jsonl`，已重命名）：

```jsonl
{"_meta": {"test_run_id": "...", "agent_name": "...", "turns_count": 2, ...}}
{"turn": 1, "user_message": "...", "assistant_text": "...", "tool_calls": ["联网搜索"], "tool_calls_raw": ["web_search"], "latency_ms": 12000, ...}
{"turn": 2, "user_message": "[HITL] 确认竞品", "assistant_text": "...", "tool_calls": ["报告生成"], ...}
```

### result.json

```json
{
  "case_id": "CASE_001",
  "passed": true,
  "score": 8.5,
  "final_verdict": "Pass",
  "calls_assertion_ok": true,
  "missing_tools": [],
  "criteria": [
    {
      "name": "一、意图识别",
      "score": 10,
      "weight": 0.15,
      "passed": true,
      "dimensions": [...]
    }
  ]
}
```

### report.md

Markdown 报告包含：session 元信息、评估结论、分节得分汇总表、主要失分点、逐维度明细。

---

## 环境变量

| 变量 | 说明 | 优先级 |
|------|------|--------|
| `LANGFUSE_PUBLIC_KEY` | Langfuse 公钥 | 高于 agent-test.yaml |
| `LANGFUSE_SECRET_KEY` | Langfuse 私钥 | 高于 agent-test.yaml |
| `LANGFUSE_BASE_URL` | Langfuse 服务地址 | 高于 agent-test.yaml |
