# Playwright 操作指引 — 创意策略 Agent（素材策略）

> 本文档描述如何操作创意策略 Agent 的 Web UI，供 Mode B 测试执行时参考。
> 在任何 playwright 操作开始前加载此文档，并在后续所有步骤中遵循。

---

## 登录

- 访问 `playwright_url` 后会自动跳转至 SSO 登录页（test-sso.meetsocial.cn）
- 填写邮箱账号前缀：`simon.sun` 和密码：`Klc987648`
- 勾选「我已阅读并同意隐私协议」复选框
- 点击「登 录」按钮，等待跳转回 Agent 页面

---

## 创建新会话

创意策略 Agent 的新会话**直接从创意首页发起**，不走「新建」侧边栏弹层。

### 步骤

1. 登录后导航至创意首页（`/creative-agent`）：
   ```bash
   playwright-cli goto "https://test-adtech-market-insight-agent.meetsocial.cn/creative-agent" --browser=chromium
   playwright-cli snapshot  # 确认页面标题为「Let's Meet As Creative」
   ```

2. 首页输入区结构：
   ```
   给我的产品  [商品链接（选填）]  设计广告创意策略方案
   [ + ]  [ 创意策略 ]                              [ 发送 ↑ ]
   ```
   - **URL 输入框**（可选）：`input[placeholder="商品链接（选填）"]`
   - **主文本区**：`div.ant-sender-input`（contenteditable，可直接 fill 或 type）
   - **附件按钮**：`button[aria-label="plus"]` 或 `img "plus"` 的父按钮
   - **发送按钮**：`img[alt="发送"]` 的父元素

3. 填写初始消息（根据用例 `user_query` 和 `fixtures`）：

   **有商品链接时**：
   ```bash
   playwright-cli snapshot  # 获取 URL 输入框 ref（如 e342）
   playwright-cli fill <url_input_ref> "<商品URL>"
   # 若需要在默认模板外追加文字，找到主文本区 ref 并 fill/type
   ```

   **有附件（fixtures）时**，在发送前上传文件：
   ```bash
   playwright-cli snapshot  # 找到 + 按钮 ref
   playwright-cli click <plus_button_ref>
   playwright-cli upload "<absolute_path_to_fixture>"
   playwright-cli snapshot  # 确认文件已附加在输入框上方
   ```

4. 点击发送按钮：
   ```bash
   playwright-cli click <send_button_ref>
   playwright-cli snapshot  # 确认 URL 已跳转为 /creative-agent/{id}
   ```

---

## Session ID 提取（用于 Langfuse 查询）

- 发送初始消息后，页面 URL 格式为 `/creative-agent/{id}`
  - 示例：`/creative-agent/4405`
- Langfuse `session_id` = `"creative-agent-{id}"`
  - 示例：`"creative-agent-4405"`
- **重要**：`langfuse_session_id` 必须在创建会话、提取 session_id 之后写入 context.json

---

## 输入消息与发送（会话中）

会话建立后的追问使用聊天输入框：

- 输入框 placeholder：`发消息，输入文本或 / 选择文件`
- 输入完成后点击右侧「发送」图标：
  ```bash
  playwright-cli fill <textarea_ref> "<追问内容>" --submit
  ```

---

## 浏览器操作关键标识

Mode B 步骤 5 的代码模板中需要以下项目专属值：

| 标识 | 本项目的值 | 用途 |
|------|-----------|------|
| DONE 判断方式 | `textarea[placeholder="发消息，输入文本或 / 选择文件"].isDisabled() === false` | 步骤 5b 轮询退出条件：主聊天输入框 enabled = Agent 完成 |
| 消息内容选择器 | `.ant-bubble-body` | 步骤 5c 提取 assistant_text |
| HITL 检测方式 | 同 Mode B 通用模板 | 步骤 5b：最后一条 bubble 内出现非空按钮文本 = HITL |

---

## 创意策略输出与图片下载

Agent 完成后，最后一条 assistant 消息包含：
- **路径汇总表格**：序号 / 路径名称 / 核心主张 / 心理钩子 / 目标人群
- **每条路径的创意卡片图片**：点击任意图片可在右侧打开画布面板（自由画布 / 在线文档两种视图）

当前版本**无内置下载按钮**。图片以 OSS 预签名 URL 形式嵌在 DOM 中，需在 Agent 完成后立即提取并下载（预签名 URL 有时效，不可存留待后续使用）。

### 提取图片 URL

```bash
img_json=$(playwright-cli run-code "async page => {
  const imgs = await page.locator('.ant-bubble-body img[alt]').all();
  const seen = new Set();
  const result = [];
  for (const img of imgs) {
    const src = await img.getAttribute('src');
    const alt = await img.getAttribute('alt');
    if (src && src.includes('mcp_image_gen') && alt && alt.length > 2 && !seen.has(src)) {
      seen.add(src);
      result.push(JSON.stringify({ alt, src }));
    }
  }
  return result.join('\n');
}" 2>/dev/null)
echo "$img_json"
```

返回每张图片一行 JSON（`{"alt":..., "src":...}`），逐行解析即可。

> **注意**：`playwright-cli run-code` 的 stdout 带有 `### Result` 头部和引号包裹，直接 `json.loads` 整体输出会报错。上方代码使用 `result.join('\n')` 逐行输出，绕过该问题。若需接收数组格式，须先提取首个 `[` 到末尾 `]` 之间的内容再解析。

### 下载图片

```bash
# 将上方输出逐行解析后 curl 下载（每行一个 JSON 对象）
echo "$img_json" | python3 -c "
import sys, json, subprocess, re, os
items = [json.loads(l) for l in sys.stdin if l.strip().startswith('{')]
out_dir = 'reports/<test_run_id>/images'
os.makedirs(out_dir, exist_ok=True)
for i, item in enumerate(items, 1):
    # 取描述前10个字作为文件名
    name = re.sub(r'[^\w\u4e00-\u9fff]', '', item['alt'])[:10]
    filename = f'{out_dir}/path_{i:03d}_{name}.png'
    subprocess.run(['curl', '-s', '-o', filename, item['src']], check=True)
    print(f'Downloaded: {filename}')
"
```

> **注意**：若某张图片的 OSS URL 签名已失效（页面本身也加载失败），下载结果为 XML 错误文件而非图片，可通过 `file <filename>` 确认并跳过。

---

## 多 Agent 类型说明

| URL 前缀 | Agent 名称 |
|---------|-----------|
| `/ecbr-rec/` | 洞察分析 |
| `/creative-agent/` | 创意策略（本项目） |
| `/placement-agent/` | 投放策略 |
