# 模式 B：执行测试（playwright-cli + Langfuse）

## 核心原则

**所有状态通过文件持久化，不依赖 MCP server。**

浏览器操作全部由 Claude 通过 `playwright-cli` Bash 命令完成：
- `playwright-cli open <url>` — 打开浏览器并导航
- `playwright-cli goto <url>` — 在已开启的会话中跳转
- `playwright-cli snapshot` — 获取页面快照（含 ref）
- `playwright-cli click <ref>` — 点击元素
- `playwright-cli fill <ref> "<text>" [--submit]` — 填写输入框
- `playwright-cli type "<text>"` — 向当前焦点输入
- `playwright-cli upload <file>` — 上传文件

---

## 完整执行流程

### 步骤 1：读取用例

```
Read: project/{project_name}/cases.csv
```

找到匹配 `case_id` 的行，手动解析关键字段：
- `expected_tools`：按 ` / ` 分隔为列表
- `max_turns`：转为整数
- `fixtures`：按 ` / ` 分隔为列表（若有）

直接读取：`case_id`、`user_query`、`final_intent`、`max_turns`（int）、`expected_tools`（列表）、`fixtures`（如有）、`operation_guide`（如有）。

若用例包含 `operation_guide` 字段，立即读取该文件（路径相对于项目根目录 `/Users/simon/Documents/Repo/ATM-Playwright/`），并在后续所有浏览器操作中严格遵循其中的登录、导航、输入、等待等操作说明。

### 步骤 2：初始化 session

生成 `test_run_id`（格式：`<case_id>_<yyyymmdd_HHMMSS>`），写入 context.json：

```
Write: reports/{test_run_id}/context.json
```

内容：
```json
{
  "test_run_id": "<test_run_id>",
  "playwright_url": "<Agent Web UI URL>",
  "langfuse_session_id": "<与 Agent 上报 trace 一致的 session_id>",
  "agent_name": "<agent 名称>",
  "project_name": "<项目目录名>",
  "started_at": "<ISO-8601 UTC>",
  "fixtures_abs": ["/绝对路径/project/{project_name}/{fixture}"]
}
```

**fixtures 路径解析：**
- 从 case 的 `fixtures` 字段读取相对路径列表（按 ` / ` 分隔）
- 拼接绝对路径：`/Users/simon/Documents/Repo/ATM-Playwright/project/{project_name}/{fixture}`

> 若 `langfuse_session_id` 需从页面 URL 提取（如 operation_guide.md 中说明），本步骤须在步骤 3（导航并提取 session_id）之后调用。

### 步骤 3：打开 Agent 页面

```bash
playwright-cli open <playwright_url> --browser=chromium
playwright-cli snapshot
```

确认页面加载完成，找到输入框。

### 步骤 4（如有 fixtures）：上传文件

```bash
playwright-cli upload <absolute_path>
```

在发送 user_query 前完成上传，用 snapshot 确认文件已附加。

### 步骤 5：对话循环（最多 max_turns 次）

**每次循环 = 一个 Agent 处理单元 = 一条 Langfuse Trace = turns.jsonl 中一条记录。**

HITL 确认会触发 Langfuse 新 Trace，因此每次点击 HITL 即开启新一轮循环，不计入 max_turns。每条 Trace 结束时（无论 DONE 还是 HITL）均独立提取一次页面全文。

> 以下代码中的 CSS selector（`.ant-bubble-body`）为示例值，**以当前项目 operation_guide.md「浏览器操作关键标识」节的值为准**（DONE 判断方式：`textarea.isDisabled() === false`）。

**本阶段只做浏览器交互，不查询 Langfuse。**

#### 5a. 发送用户消息（仅用户主动发消息时执行）

初始消息或追问时发送：
```bash
playwright-cli fill <输入框ref> "<用户消息>" --submit
```

HITL 确认不走此步骤，直接执行 5d，点击后回到 5b。

#### 5b. 等待当前 Trace 完成或 HITL 暂停

**单次 waitForFunction（替代 bash 轮询，2s 间隔，减少 snapshot 开销）**

超时时间：**10 分钟**（`timeout: 600000`）

> DONE selector 以 operation_guide.md「浏览器操作关键标识」中的值为准；HITL 检测检查最后一条气泡内是否有可见非空按钮，**无需关键词列表**。

```bash
# 消息气泡 selector 由执行时从 operation_guide.md 读取后内联（下方为示例值）
status_json=$(playwright-cli run-code "async page => {
  const BUBBLE_SELECTOR = '.ant-bubble-body';  // ← 替换为项目实际 selector
  try {
    const handle = await page.waitForFunction(
      (bubbleSel) => {
        const ta = document.querySelector('textarea[placeholder=\"发消息，输入文本或 / 选择文件\"]');
        if (ta && !ta.disabled) return JSON.stringify({ status: 'DONE' });
        const bubbles = document.querySelectorAll(bubbleSel);
        if (bubbles.length > 0) {
          const last = bubbles[bubbles.length - 1];
          const btns = [...last.querySelectorAll('button')];
          const meaningful = btns.filter(b => b.offsetParent !== null && b.textContent.trim());
          if (meaningful.length > 0)
            return JSON.stringify({ status: 'HITL', hitlText: meaningful.map(b => b.textContent.trim()).join('|') });
        }
        return null;
      },
      BUBBLE_SELECTOR,
      { timeout: 600000, polling: 2000 }
    );
    return await handle.jsonValue();
  } catch (e) {
    return JSON.stringify({ status: 'TIMEOUT' });
  }
}" 2>/dev/null)
turn_status=$(echo "$status_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read() or '{}').get('status','TIMEOUT'))")
echo "$turn_status"
```

轮询结果：
- `DONE` — 输入框变为 enabled（Agent 完成且页面稳定，含文件卡片加载完成）→ 执行 5c → 5e 判断
- `HITL` — HITL 确认按钮出现（Agent 暂停等待确认）→ 执行 5c → 5d 点击确认 → **返回 5b 继续轮询，不退出 execute**
- `TIMEOUT` — 10 分钟内未收到 DONE/HITL → 执行 5c，**强制退出 execute**，进入步骤 6

> HITL 确认按钮文案因用例而异，以 `operation_guide.md` 中的关键词列表为准。

#### 5c. 提取当前 Trace 的页面全文

**无论 DONE / HITL / TIMEOUT，均立即提取页面全文**，这是当前 Trace 对应的 assistant_text：

```bash
playwright-cli run-code "async page => {
  const bubbles = await page.locator('.ant-bubble-body').all();
  const last = bubbles[bubbles.length - 1];
  return await last.innerText();
}"
```

暂存文本，标记为**当前 Trace** 的 assistant_text，供步骤 6c 使用。

⚠️ **严禁对提取文本进行总结、改写或添加任何执行者注释（如 `[注意：...]`）。assistant_text 只记录页面事实原文，run-code 返回什么就存什么。**

#### 5d. 处理 HITL（5b 返回 HITL 时执行）

先 snapshot 看清 Agent 呈现的交互界面，再按实际情况操作：

| HITL 类型 | 操作 |
|-----------|------|
| 纯确认按钮 | `playwright-cli click <按钮ref>` |
| 表单填写 + 提交 | `playwright-cli fill <ref> "<内容>" --submit` |
| 下拉/单选选择 | `playwright-cli click <选项ref>`，再点确认 |
| 混合（填写 + 选择 + 确认）| 按界面顺序逐步操作，最后点提交/确认 |

操作完成后**返回 5b**，等待下一条 Trace 完成。

#### 5e. 判断是否继续（5b 返回 DONE 时执行）

**退出 execute 的唯一条件**：输入框 enabled（DONE）**且** `final_intent` 描述的目标已达成

- `final_intent` 已满足 → **退出 execute**，进入步骤 6
- `final_intent` 未满足 且还有剩余 max_turns → 生成追问消息，跳回 5a
- `final_intent` 未满足 且 max_turns 已耗尽 → **退出 execute**，进入步骤 6（记录为未完成）

> **TIMEOUT 处理**：5b 返回 TIMEOUT 时，仅中断当前对话循环（步骤 5），步骤 6（Langfuse 拉取）、步骤 7（写出 turns.jsonl）照常执行，Mode C 评估可基于已收集的数据正常进行。assistant_text 保留当前页面原文，不添加任何注释。

---

### 步骤 6：拉取 Langfuse 数据并记录轮次

**无论对话正常完成还是异常中断，都在此步骤统一拉取。**

#### 6a. 等待 trace 刷新

等待 3-5 秒，确保 Agent 已将 trace 上报至 Langfuse。

#### 6b. 拉取全部 traces

读取 `reports/{test_run_id}/context.json` 获取 `langfuse_session_id`，然后运行 CLI 脚本：

```bash
.venv/bin/python src/tools/query_langfuse.py \
  --session-id <langfuse_session_id> \
  [--min-timestamp <ISO-8601>]
```

返回字段：
- `found: true` — 包含 `traces[]`（每条 trace 含 `tool_calls` / `tool_call_counts` / `tool_call_failures` / `latency_ms` / `tool_latency_ms` / `llm_latency_ms` / `tokens` / `observations`）、汇总的 `tool_calls`、`tool_call_counts`、`tool_call_failures`、`latency_ms`、`tool_latency_ms`、`llm_latency_ms`、`input_tokens`、`output_tokens`
- `found: false` — trace 尚未同步，等待 3-5 秒后重试一次
- `traces_count` — 本 session 共有几条 trace

> 注意：Langfuse 响应**不包含 `assistant_text`**，对话内容由步骤 5c 的页面提取负责。

#### 6c. 按 trace 逐条记录对话上下文（在工作记忆中累积）

每条 trace 对应一条 context 记录，暂存在工作记忆中，不立即写文件：
- `user_message`：根据 trace 位置推断：第 1 条 = 初始 user_query；HITL trace = `"[HITL] <确认操作描述>"`；追问 trace = 追问消息
- `assistant_text`：**步骤 5c 中该 Trace 结束时提取的页面原始全文**，与 run-code 返回内容完全一致，严禁总结或添加任何注释；每条 Trace 各有一次独立提取；不从 Langfuse 取
- `latency_ms` / `input_tokens` / `output_tokens`：来自该 trace

> **tool_calls 和 observations 均不写入 context.jsonl**，由步骤 7b 单独存入 `traces.jsonl`。

> 若 Langfuse 完全不可用（`found: false` 重试后仍无），fallback：在报告中标注"未能从 Langfuse 获取"。assistant_text 仍用页面提取，不受影响。

---

### 步骤 6.5：来源核验

Mode B 完成后可选执行，详见 `modes/d-verify.md`。

---

### 步骤 7a：写出 context.jsonl

将步骤 6c 累积的对话上下文列表写出为 JSONL 文件（**仅含对话内容，无 tool call 信息**）：

```
Write: reports/{test_run_id}/context.jsonl
```

首行为 `_meta`，后续每行一条对话记录：

```jsonl
{"_meta": {"test_run_id": "...", "agent_name": "...", "playwright_url": "...", "langfuse_session_id": "...", "started_at": "...", "ended_at": "<now ISO-8601 UTC>", "turns_count": N}}
{"turn": 1, "user_message": "...", "assistant_text": "...", "latency_ms": 12000, "input_tokens": 500, "output_tokens": 200}
{"turn": 2, "user_message": "[HITL] 确认竞品", "assistant_text": "...", "latency_ms": 8000}
```

### 步骤 7b：写出 traces.jsonl

将 Langfuse 原始 trace 数据（含完整 tool_calls、counts、failures、observations）写出为 JSONL 文件：

```
Write: reports/{test_run_id}/traces.jsonl
```

首行为 `_meta`，后续每行一条 trace（直接取 query_langfuse.py 返回的 `traces[]` 各元素）：

```jsonl
{"_meta": {"test_run_id": "...", "langfuse_session_id": "...", "traces_count": N}}
{"trace_id": "...", "timestamp": "...", "tool_calls": [...], "tool_call_counts": {...}, "tool_call_failures": {...}, "latency_ms": ..., "tool_latency_ms": ..., "llm_latency_ms": ..., "input_tokens": ..., "output_tokens": ..., "observations": [...]}
{"trace_id": "...", ...}
```

---

## 注意事项

- `langfuse_session_id` 必须与 Agent 在运行时上报给 Langfuse 的 session_id 一致。如不确定，可查看 Langfuse 控制台，观察用例执行后产生的新 session。
- Langfuse trace 可能有 1-10 秒延迟，`found=false` 时稍等再试。
- 每次 HITL 确认触发 Langfuse 新 Trace = turns.jsonl 中独立一条记录；步骤 5c 确保每条 Trace 结束时均有独立的页面全文快照。
- 若 Agent 回复异常中断（页面报错、超时），仍执行步骤 6 拉取已产生的 traces，确保有据可查。
- **过程文件**（todowrite 输出、规划草稿等）不计入结果文件，不触发来源核验；只有聊天区域出现下载入口的**结果输出文件**才需下载并作为核验依据。
