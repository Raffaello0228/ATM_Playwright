# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ATM-Playwright is an AI Agent automated testing framework. Claude drives the browser via `playwright-cli`, queries Langfuse traces via a CLI script, and reads/writes test artifacts directly as files. There is no MCP server — all state is file-based.

## Setup

```bash
# Install dependencies
pip install -e .

# Configure Langfuse credentials
cp agent-test.example.yaml agent-test.yaml
# Edit agent-test.yaml with real Langfuse credentials and agent URL
```

## Directory Structure

- `project/<project_name>/` — CSV test cases and upload assets for that suite; optional `tools.json` listing the agent's tools (name + description)
- `reports/<test_run_id>/` — Per-run output: `context.jsonl`, `traces.jsonl`, `result.json`, `report.md`
- `reports/batches/` — Batch summary files: `{batch_id}.json`
- `src/tools/query_langfuse.py` — CLI: query Langfuse traces for a session, outputs JSON
- `src/tools/update_batch.py` — CLI: append a test run's result to a batch summary file
- `src/adapters/langfuse_client.py` — Langfuse REST API client (traces, observations, token/latency extraction)
- `modes/` — Mode-specific instructions (a-design.md, b-execute.md, c-evaluate.md)

## CLI Tools

### query_langfuse.py
```bash
.venv/bin/python src/tools/query_langfuse.py \
  --session-id <langfuse_session_id> \
  [--min-timestamp <ISO-8601>] \
  [--limit 50]
```
Outputs JSON: `{ok, found, tool_calls, tool_call_counts, tool_call_failures, latency_ms, tool_latency_ms, llm_latency_ms, input_tokens, output_tokens, traces_count, traces[]}`

### update_batch.py
```bash
.venv/bin/python src/tools/update_batch.py \
  --batch-id <batch_id> \
  --test-run-id <test_run_id> \
  [--project-name <name>] \
  [--agent-version <version>]
```
Appends `result.json` to `reports/batches/{batch_id}.json` and recomputes pass rate / avg score.

## Three Operating Modes

**Mode A (Design):** Create CSV test cases under `project/<project_name>/`. Use the Write tool directly to save case files.

**Mode B (Execute):** Claude drives the browser with `playwright-cli`, writes session context to `reports/{test_run_id}/context.json`, runs `query_langfuse.py` to get tool calls, then writes `context.jsonl` (conversation) and `traces.jsonl` (full Langfuse data) at end.

**Mode C (Evaluate):** Read `context.jsonl` + `traces.jsonl` + case CSV, verify `expected_tools`, score each rubric dimension, write `result.json` and `report.md` directly. Optionally run `update_batch.py` to register the result in a batch.

## Key Design Points

- **No MCP server.** All state is file-based. Claude uses Read/Write/Edit tools for file operations.
- **Langfuse credentials** come from `agent-test.yaml` or env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`).
- **`test_run_id` format:** `<case_id>_<yyyymmdd_HHMMSS>` — used as the report subdirectory name.
- **Langfuse trace delay:** Traces may take 1–10 seconds to appear; `query_langfuse.py` returns `found: false` — wait and retry.
- **Batch tracking:** Pass `--batch-id` to `update_batch.py` after each Mode C evaluation to accumulate results for cross-run comparison.
