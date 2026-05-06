# 模式 D：来源核验

Mode B 完成后、Mode C 评估前执行（可选）。

---

## 触发条件

| 优先级 | 条件 | 核验依据 |
|--------|------|---------|
| 1（优先）| Agent 生成了可下载的**结果输出文件**（report.md、analysis.xlsx 等） | 报告文件内容 |
| 2（次选）| 最终回复中包含**明确标注的数据源 URL** | 聊天文字 |
| 跳过 | 两者均无，或只有过程文件 | — |

**过程文件不触发来源核验**：todowrite 任务列表、规划草稿、临时 markdown 均属于过程文件，不计入。

---

## 执行流程

1. 从报告文件或 assistant_text 中提取数据源 URL 与 Agent 声称的参数值
2. 对每个 URL 做快照：

```bash
playwright-cli open <url> --browser=chromium
playwright-cli snapshot
```

3. 在快照中搜索声称的参数值，记录页面原文（一致 / 不一致 / 无法访问）

4. 每个 URL 核验完成后记录一条轮次：

```
atm_record_turn(
  test_run_id = "<test_run_id>",
  user_message = "[数据源快照] <url>",
  assistant_text = "来源：<url>\n- <参数名> | Agent声称: <值> | 页面原文: <值> | ✅/❌",
  tool_calls = ["来源核验"]
)
```

5. 全部 URL 核验完成后追加汇总：

```
atm_record_turn(
  test_run_id = "<test_run_id>",
  user_message = "[来源核验汇总]",
  assistant_text = "总比对参数: N\n  一致: M\n  不一致: K\n  无法访问/未找到（已排除）: J\n抓取内容准确率: M/(N-J)×100% = XX.X%",
  tool_calls = ["来源核验"]
)
```

---

## 注意事项

- 若报告为 Excel：用 `playwright-cli run-code` 或系统命令读取表格内容提取 URL 和参数值
- 若报告中无明确 URL 引用，且聊天回复中也无，跳过本模式
- 无法访问的 URL 记录后从准确率分母中排除
