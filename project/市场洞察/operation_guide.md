# Playwright 操作指引 — Marvy Agent

> 本文档描述如何操作 Marvy Agent 的 Web UI，供 Mode B 测试执行时参考。
> 在任何 playwright 操作开始前加载此文档，并在后续所有步骤中遵循。

---

## 登录

- 访问 `playwright.url` 后会自动跳转至 SSO 登录页（test-sso.meetsocial.cn）
- 填写邮箱账号前缀：`simon.sun`和密码：`Klc987648`
- 勾选「我已阅读并同意隐私协议」复选框
- 点击「登 录」按钮，等待跳转回 Agent 页面

---

## 创建新会话

- 登录后，通过以下方式打开「新建」弹层（**直接 click 新建 ref 可能无效**）：
  ```bash
  playwright-cli run-code "async page => { await page.locator('div.sidebar-transition').first().click(); }"
  playwright-cli snapshot  # 确认 ant-popover-content 已出现
  ```
- 在弹出的 popover 中找到 Agent 类型文本并点击，根据用例的 `final_intent` / `title` 选择合适的 Agent 类型：


| Agent 类型 | 适用场景           |
| -------- | -------------- |
| **洞察分析** | 商品分析、市场洞察、竞品分析 |
| **创意策略** | 创意生成、文案撰写、图片脚本 |
| **投放策略** | 投放优化、预算分配、渠道规划 |


- 点击后自动创建新会话并跳转至聊天页面

---

## Session ID 提取（用于 Langfuse 查询）

- 创建新会话后，页面 URL 格式为 `/{agent-type}/{id}`
  - 示例：`/ecbr-rec/3791`
- Langfuse `session_id` = `"{agent-type}-{id}"`
  - 示例：`"ecbr-rec-3791"`
- 此值必须在调用 `atm_start_session` 的 `langfuse_session_id` 参数中传入
- **重要**：`atm_start_session` 必须在导航、创建会话、提取 session_id 之后调用

---

## 输入消息与发送

- 聊天输入框 placeholder：「发消息，输入文本或 / 选择文件」
- 输入完成后点击右侧「发送」图标发送消息

---

## 浏览器操作关键标识

Mode B 步骤 5 的代码模板中需要以下项目专属值：

| 标识 | 本项目的值 | 用途 |
|------|-----------|------|
| DONE 判断方式 | `textarea[placeholder="发消息，输入文本或 / 选择文件"].isDisabled() === false` | 步骤 5b 轮询退出条件：主聊天输入框变为 enabled = Agent 完成。**注意**：HITL 表单中也包含 textarea，页面可能同时存在多个 textarea；必须通过 placeholder 定位主聊天输入框，而非 `.first()` |
| 消息内容选择器 | `.ant-bubble-body` | 步骤 5c 提取 assistant_text |
| HITL 检测方式 | 见下方 run-code 代码段 | 步骤 5b 轮询退出条件：最后一条 bubble 内出现非空按钮文本 = HITL |

---

## HITL（人机交互确认）

### HITL 检测代码（步骤 5b 轮询中使用）

```bash
hitl_result=$(playwright-cli run-code "async page => {
  const bubbles = await page.locator('.ant-bubble-body').all();
  const last = bubbles[bubbles.length - 1];
  const btns = await last.locator('button').all();
  const texts = [];
  for (const b of btns) texts.push(await b.innerText());
  const meaningful = texts.filter(t => t.trim());
  return meaningful.length > 0 ? 'HITL:' + meaningful.join('|') : 'NO_HITL';
}" 2>/dev/null)
if [[ "$hitl_result" == HITL:* ]]; then turn_status="HITL"; break; fi
```

已观察到的 HITL 按钮文本（供参考，不用作硬编码匹配）：`确认，开始分析` / `确认，开始抓取` / `确认，开始采集` / `调整竞品` / `确认竞品` / `需要调整链接`

部分 Agent 在执行流程中会在关键节点暂停，等待用户通过界面按钮确认后才继续。

### 识别 HITL 状态

- 「停止会话」按钮**仍然可见**，但聊天区域出现**确认/操作按钮**（如「确认，开始分析」、「调整竞品」）
- 步骤进度条停在某个节点（如 `1/3`）不再推进

> 具体操作流程（提取文本 → 点击 → 等待下一 Trace）见 Mode B 步骤 5c/5d。

### HITL 处理原则

HITL 样式不固定，无需关注具体表单结构。**检测到 HITL 后**：

1. `playwright-cli snapshot` — 查看当前界面呈现的内容和按钮
2. 根据 snapshot 和 `final_intent` 判断如何操作（填写内容、勾选选项、点击确认等）
3. 操作完成后返回 5b 继续轮询

### 注意事项

- 每次 HITL 确认在 Langfuse 中**开启新 Trace**，对应 turns.jsonl 中的独立 Turn
- 若存在多个 HITL 节点（如检查点1、检查点2），每个节点均需同样操作
- 若 Agent 要求输入内容（文本框 + 提交），使用 `playwright-cli fill <ref> "<text>" --submit` 填写

---

## 结果文件处理

部分 Agent（如洞察分析）会在回复完成后在聊天区域生成可下载的结果文件（Excel、PDF 等）。

### 识别是否生成了结果文件

Agent 回复完成后（「停止会话」消失），使用以下代码判断最后一条 assistant 消息底部是否有**总结报告类**文件卡片（同时满足两个条件：① 底部存在文件卡片，② 不是过程文件）：

```bash
# 判断 assistant 底部是否有总结报告类文件卡片（排除过程文件）
file_status=$(playwright-cli run-code "async page => {
  const bubbles = await page.locator('.ant-bubble-body').all();
  if (!bubbles.length) return 'NO_FILE';
  const lastBubble = bubbles[bubbles.length - 1];
  const text = await lastBubble.innerText();
  const lines = text.split('\n').filter(l => l.trim());
  const tail = lines.slice(-10).join('\n');
  // 条件1：末尾有类型标签（文件卡片信号）
  if (!/Markdown|Excel|PDF/i.test(tail)) return 'NO_FILE';
  // 条件2：排除过程文件（todowrite 任务列表、规划草稿、临时文件等）
  const processKeywords = ['todo', 'task', '任务', '草稿', 'draft', 'temp'];
  const isProcess = processKeywords.some(kw => tail.toLowerCase().includes(kw));
  return isProcess ? 'NO_FILE' : 'FILE_CARD_EXISTS';
}" 2>/dev/null)
echo "$file_status"
```

- `FILE_CARD_EXISTS` → 进入下方"有结果文件时的操作"两步流程
- `NO_FILE` → 本轮无结果文件，跳过此步骤继续正常记录 turn

> **为什么不用 grep**：`grep -E "pat1|pat2"` 在本机因编码 bug 静默失败；`run-code` 直接从 DOM 提取 innerText，末尾 10 行可覆盖长回复中的文件卡片，不受快照长度限制。

### 有结果文件时的操作（两步流程）

**存储位置**：下载文件统一保存到当前测试的报告目录 `reports/<test_run_id>/`，与 `turns.jsonl` 放在一起。

**第一步：点击文件卡片，打开右侧文件查看器**

```bash
# 在 snapshot 中找到文件卡片 ref（如 e216），点击打开右侧 viewer 面板
playwright-cli click <文件卡片ref>
# 确认 viewer 已打开（页面右侧出现内容面板，顶部有「导出」按钮）
```

> 注意：文件卡片位于 assistant 消息最底部的文件列表中，不是云形下载图标，而是"文件名 + 类型标签"组合的卡片。点击后右侧会滑出文件预览面板，顶部出现「导出」按钮。

**第二步：拦截 download 事件并保存（不要直接 click，否则落到系统 Downloads）**

```bash
playwright-cli run-code "async page => {
  const [download] = await Promise.all([
    page.waitForEvent('download', {timeout: 15000}),
    page.locator('button:has-text(\"导出\")').first().click()
  ]);
  const filename = download.suggestedFilename();
  await download.saveAs('reports/<test_run_id>/' + filename);
  return filename;
}"
```

1. 将返回的文件名记录下来，在本轮 `assistant_text` 中注明：`[下载报告] reports/<test_run_id>/<filename>`
2. **重要**：下载动作属于当前轮次的一部分，**无需另起新轮**

### 结合来源核验

- 若本轮**有下载报告**，来源核验步骤（步骤 5.5）以**报告内容**为准提取数据源 URL 和声称参数值，而非聊天区域的文字回复
- 若报告为 Excel：使用 `playwright-cli run-code` 或系统命令读取表格内容，提取其中的 URL 和参数值
- 若报告为 PDF：读取文件文本内容，提取其中的 URL 和参数值
- 若报告中无明确 URL 引用，且聊天回复中也无明确 URL 引用，步骤 5.5 跳过

---

## 多 Agent 类型说明


| URL 前缀              | Agent 名称       |
| ------------------- | -------------- |
| `/ecbr-rec/`        | 洞察分析（ecbr-rec） |
| `/creative-agent/`  | 创意策略           |
| `/placement-agent/` | 投放策略           |


