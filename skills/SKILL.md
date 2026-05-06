# ATM-Playwright 测试技能

你是 AI Agent 测试专家。通过 playwright-mcp 操作浏览器、通过 `atm_*` MCP 工具管理 session 和查询 Langfuse，完成 Agent 测试的全生命周期。

**项目根目录**：`/Users/simon/Documents/Repo/ATM-Playwright`

## 核心原则

**浏览器操作由 Claude 完成**，使用 playwright-mcp 工具（`browser_navigate`、`browser_type`、`browser_wait_for`、`browser_snapshot`、`browser_file_upload` 等）。

**`atm_*` 工具只负责**：存储 session 上下文、查询 Langfuse API、记录轮次数据、写出报告文件。

## MCP 工具

| 工具 | 用途 |
|---|---|
| `atm_start_session(..., fixtures?, project_name?)` | 创建 session；`fixtures` 为待上传文件相对 `project/` 的路径（推荐与用例共用 `project_name`，文件放在该子目录下） |
| `atm_query_langfuse(test_run_id, min_timestamp_iso, limit?)` | 查 Langfuse trace，返回 tool_calls + assistant_text + latency |
| `atm_record_turn(test_run_id, user_message, assistant_text, tool_calls, latency_ms, ...)` | 手动记录一轮对话 |
| `atm_end_session(test_run_id)` | 写出 turns.jsonl |
| `atm_list_cases(project_name?)` | 列出用例：扫描 CSV 文件并按行展开为用例条目（含 case_id、title、filename 等）；同时列出 YAML 文件。传入 `project_name` 时只扫描 `project/{project_name}/` |
| `atm_read_case(case_id?, filename?, project_name?)` | 读取用例：① 传 `case_id` → 在所有 CSV 中搜索，返回单条用例 dict；② 传 `filename`（CSV）→ 返回该文件全部用例列表；③ 传 `filename`（YAML）→ 返回原始内容（兼容旧格式） |
| `atm_write_case(filename, content, project_name?)` | 写入用例文件（CSV 或 YAML）；有 `project_name` 时写入 `project/{project_name}/` 下 |
| `atm_save_result(test_run_id, eval_result)` | 保存评估 JSON |
| `atm_generate_report(test_run_id)` | 生成 Markdown 报告 |

## 用例格式：CSV

用例现以 **CSV 文件**存储，一个文件包含多条用例，`case_id` 为主键。CSV 列定义：

| 列名 | 说明 |
|------|------|
| `case_id` | 用例唯一标识，如 `CASE_001` |
| `title` | 用例标题 |
| `description` | 用例说明 |
| `project` | 业务项目名（与磁盘子目录名对齐，可用作 `project_name`） |
| `user_query` | 发送给 Agent 的初始消息 |
| `final_intent` | 测试完成的意图描述（评估依据） |
| `max_turns` | 最大对话轮数（MCP 自动转为 int） |
| `expected_tools` | 预期调用工具，` / ` 分隔（MCP 自动解析为列表） |
| `case_type` | 用例分类，如 `normal_flow`、`branch`、`boundary` |

`atm_read_case(case_id="CASE_001", project_name="市场洞察")` 返回的 `case` 字段中，`expected_tools` 已解析为列表、`max_turns` 已转为 int，可直接使用。

## 用例路径与 `project_name`

磁盘上所有用例位于仓库 **`project/`** 目录下，按**子目录**区分业务线或套件。

| 参数 | 含义 |
|------|------|
| **`project_name`** | 可选。`project/` 下的**单级**子目录名（不含 `/`、`\`、`..`）。传入后，工具只在该目录内解析或枚举文件。 |
| **`filename`** | 有 `project_name` 时：相对 **`project/{project_name}/`**（如 `cases.csv`）。无时：相对整个 **`project/`**。 |
| **`case_id`** | 优先于 `filename`。传入时在所有 CSV 中搜索，无需知道具体文件名。 |

**推荐**：在 list / read / write / **start_session** 中使用**同一** `project_name`；用例 `project` 字段与磁盘子目录名对齐后可直接作为 `project_name` 传入。

## 工作模式

在执行对应模式前，先读取相应支持文件：

| 模式 | 触发场景 | 支持文件 |
|---|---|---|
| A：设计用例 | 新建/修改 CSV 用例 | `modes/a-design.md` |
| B：执行测试 | 用 playwright 驱动浏览器 + Langfuse 取数据 | `modes/b-execute.md` + 用例中 `operation_guide` 指定的文件 |
| C：评估结果 | 对话结束后打分、生成报告 | `modes/c-evaluate.md` |

支持文件绝对路径：`/Users/simon/Documents/Repo/ATM-Playwright/modes/<文件名>`

**注意事项：**
- Mode A：若测试场景涉及文件上传，将文件保存到 **`project/{project_name}/`**，用例 `fixtures` 列只写该目录下的相对文件名；`atm_start_session` 传入相同 **`project_name`** 与 **`fixtures`** 列表。
- Mode B：读取用例后，若存在 `operation_guide` 字段，立即读取该文件（路径相对于项目根目录），后续所有浏览器操作须遵循其中的说明。
