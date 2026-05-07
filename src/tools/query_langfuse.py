"""Langfuse session trace 查询 CLI。

用法：
    .venv/bin/python src/tools/query_langfuse.py \\
        --session-id <langfuse_session_id> \\
        [--min-timestamp <ISO-8601>] \\
        [--limit 50]

输出（stdout，单行 JSON）：
    成功：{"ok": true, "found": true, "tool_calls": [...], "tool_calls_raw": [...],
            "latency_ms": ..., "input_tokens": ..., "output_tokens": ...,
            "traces_count": N, "traces": [...]}
    无 trace：{"ok": true, "found": false}
    失败：{"ok": false, "error": "..."}

复用 src/adapters/langfuse_client.py，
并行获取 trace 详情（ThreadPoolExecutor），比串行 N+1 快约 5 倍。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 将 src/ 加入 sys.path，使 adapters / core 可正常导入
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# 凭证加载
# ---------------------------------------------------------------------------

def _load_creds() -> tuple[str, str, str]:
    """读取 Langfuse 凭证，返回 (public_key, secret_key, base_url)。

    优先级：环境变量 > agent-test.yaml。
    """
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    bu = os.environ.get("LANGFUSE_BASE_URL", "")
    if pk and sk and bu:
        return pk, sk, bu

    # fallback：读 agent-test.yaml（从 repo 根目录查找）
    repo_root = Path(__file__).parent.parent.parent
    for name in ("agent-test.yaml", "agent-test.yml"):
        path = repo_root / name
        if path.exists():
            try:
                import yaml
                cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                lf = cfg.get("langfuse") or {}
                return (
                    lf.get("public_key") or pk,
                    lf.get("secret_key") or sk,
                    lf.get("base_url") or bu,
                )
            except Exception:
                pass
    return pk, sk, bu


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="查询 Langfuse session 下的全部 trace 并聚合输出"
    )
    parser.add_argument("--session-id", required=True, help="Langfuse session_id")
    parser.add_argument(
        "--min-timestamp",
        default=None,
        help="只返回此时间之后的 trace（ISO-8601，可选）",
    )
    parser.add_argument("--limit", type=int, default=50, help="最多获取 trace 数，默认 50")
    args = parser.parse_args()

    # --- 凭证校验 ---
    pk, sk, base_url = _load_creds()
    if not (pk and sk and base_url):
        _exit_error("Langfuse 凭证未配置，请设置环境变量或填写 agent-test.yaml")

    # --- 导入客户端 ---
    try:
        from adapters.langfuse_client import LangfuseQueryClient
    except ImportError as e:
        _exit_error(f"无法导入 LangfuseQueryClient: {e}")

    # --- 拉取 trace 列表 ---
    lf = LangfuseQueryClient(public_key=pk, secret_key=sk, base_url=base_url)
    try:
        traces = lf.fetch_session_traces(
            session_id=args.session_id,
            min_timestamp_iso=args.min_timestamp,
            limit=args.limit,
        )
    except Exception as e:
        lf.close()
        _exit_error(f"Langfuse API 请求失败: {e}")

    if not traces:
        lf.close()
        _output({"ok": True, "found": False,
                 "message": "未找到 trace，Agent 可能尚未将数据刷入 Langfuse，等待 2-5 秒后重试"})
        return

    # --- 并行获取 trace 详情（ThreadPoolExecutor，替代串行 N+1）---
    trace_results = []
    with ThreadPoolExecutor(max_workers=min(10, len(traces))) as pool:
        future_map = {
            pool.submit(lf.get_trace_details, t["id"]): t
            for t in traces
        }
        for future in as_completed(future_map):
            try:
                full_trace = future.result()
                trace_results.append(lf.build_trace_result(full_trace))
            except Exception:
                pass  # 跳过获取失败的单条 trace

    # 按 timestamp 升序排列，保持与 Langfuse 原始顺序一致
    trace_results.sort(key=lambda r: r.timestamp)

    lf.close()

    if not trace_results:
        _exit_error("所有 trace 详情获取失败")

    # --- 聚合并输出 ---
    aggregated = lf.build_aggregated_result(trace_results)
    _output({"ok": True, **aggregated})


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _output(data: dict) -> None:
    """将结果序列化为单行 JSON 输出到 stdout。"""
    print(json.dumps(data, ensure_ascii=False))


def _exit_error(msg: str) -> None:
    """输出错误 JSON 并以非零状态退出。"""
    _output({"ok": False, "found": False, "error": msg})
    sys.exit(1)


if __name__ == "__main__":
    main()
