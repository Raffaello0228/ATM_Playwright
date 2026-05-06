# Playwright 操作指引 — [Agent 名称]

> 本文档描述如何操作 [Agent 名称] 的 Web UI，供 Mode B 测试执行时参考。
> 在任何 playwright 操作开始前加载此文档，并在后续所有步骤中遵循。

---

## 登录

<!-- 描述如何进入 Agent 页面。常见方式：
- 直接访问无需登录
- 需要账号密码登录（填写步骤）
- 需要 SSO 跳转（说明跳转 URL 和操作步骤）
-->

- 访问 `playwright_url`（来自 agent-test.yaml 的 `url` 配置）
- [填写具体登录步骤，例如：]
  - 填写邮箱：`simon.sun`
  - 填写密码：`Klc987648`
  - 点击「登录」按钮，等待跳转

---

## 创建新会话

<!-- 描述如何在 Agent UI 中新建一个对话 session。
包括：点击什么按钮、选择什么 Agent 类型、如何确认进入聊天页面。-->

- [例如：] 点击左侧「新建对话」按钮
- 在弹出的选项中选择合适的 Agent 类型（根据用例的 final_intent 判断）
- 等待聊天页面加载完成

---

## Session ID 提取（用于 Langfuse 查询）

<!-- 说明创建新会话后如何从 URL 或页面中提取 langfuse_session_id。
必须与 Agent 上报给 Langfuse 的 session_id 保持一致。-->

- 创建新会话后，页面 URL 格式为 `[URL 格式，例如 /{agent-type}/{id}]`
- Langfuse `session_id` = `"[拼接规则，例如 {agent-type}-{id}]"`
- **重要**：必须在导航、创建会话、提取 session_id 之后再写入 context.json

---

## 输入消息与发送

<!-- 描述聊天输入框的 placeholder 文本（用于 playwright 定位），以及发送方式。-->

- 聊天输入框 placeholder：「[输入框 placeholder 文本]」
- [发送方式：点击按钮 / 按 Enter 键]

---

## 浏览器操作关键标识

Mode B 步骤 5 的代码模板中需要以下项目专属值：

| 标识 | 本项目的值 | 用途 |
|------|-----------|------|
| DONE 判断方式 | `textarea[placeholder="[输入框placeholder]"].isDisabled() === false` | 步骤 5b 轮询退出条件 |
| 消息内容选择器 | `[聊天气泡 CSS selector，例如 .chat-bubble]` | 步骤 5c 提取 assistant_text |
| HITL 按钮关键词 | `['[关键词1]', '[关键词2]']` | 步骤 5b 检测 HITL 暂停状态 |

**关于 DONE 判断**：
- 找到主聊天输入框的 placeholder 文本，用 `textarea[placeholder="..."]` 精确定位
- 不要用 `.first()`，因为 HITL 表单中也可能包含 textarea，会误匹配

**关于 HITL 按钮关键词**：
- 列出 Agent 在 HITL 暂停时可能出现的所有按钮文字（部分匹配即可）
- 例如：`['确认', '开始分析', '调整', '取消']`
- 如果 Agent 不支持 HITL，此字段留空列表 `[]`

---

## HITL（人机交互确认）

<!-- 描述该 Agent 是否有 HITL 交互。若无 HITL，删除本节。-->

### 识别 HITL 状态

- [描述 HITL 出现时的页面特征，例如：]
  - 聊天区域出现确认/操作按钮（如「确认，开始分析」）
  - 步骤进度条停在某个节点不再推进

### 操作方式

| HITL 类型 | 操作 |
|-----------|------|
| 纯确认按钮 | `playwright-cli click <按钮ref>` |
| 表单填写 + 提交 | `playwright-cli fill <ref> "<内容>" --submit` |

### 注意事项

- 每次 HITL 确认在 Langfuse 中**开启新 Trace**，对应 turns.jsonl 中的独立 Turn
- 若存在多个 HITL 节点，每个节点均需同样操作

---

## 结果文件处理（可选）

<!-- 若 Agent 会生成可下载的结果文件（报告、Excel、PDF 等），填写本节。
若无，删除本节。-->

### 识别是否生成了结果文件

Agent 回复完成后，检查聊天区域是否出现文件卡片：

```bash
file_status=$(playwright-cli run-code "async page => {
  // [根据实际 UI 调整检测逻辑]
  const bubbles = await page.locator('[消息气泡selector]').all();
  if (!bubbles.length) return 'NO_FILE';
  const lastBubble = bubbles[bubbles.length - 1];
  const text = await lastBubble.innerText();
  // 检测文件类型关键词
  if (/Markdown|Excel|PDF/i.test(text)) return 'FILE_CARD_EXISTS';
  return 'NO_FILE';
}" 2>/dev/null)
echo "$file_status"
```

### 有结果文件时的操作

```bash
# 1. 点击文件卡片打开预览
playwright-cli click <文件卡片ref>

# 2. 拦截 download 事件并保存到报告目录
playwright-cli run-code "async page => {
  const [download] = await Promise.all([
    page.waitForEvent('download', {timeout: 15000}),
    page.locator('button:has-text(\"[导出按钮文字]\")').first().click()
  ]);
  const filename = download.suggestedFilename();
  await download.saveAs('reports/<test_run_id>/' + filename);
  return filename;
}"
```

下载完成后，在 assistant_text 中注明：`[下载报告] reports/<test_run_id>/<filename>`
