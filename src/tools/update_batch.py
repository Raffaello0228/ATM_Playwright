"""批次摘要更新 CLI。

将单次测试运行的评估结果追加到批次摘要文件 reports/batches/{batch_id}.json，
并重新计算 summary（通过率、平均分等）。

用法：
    .venv/bin/python src/tools/update_batch.py \\
        --batch-id <batch_id> \\
        --test-run-id <test_run_id> \\
        [--project-name <project_name>] \\
        [--agent-version <version>]

批次文件路径：reports/batches/{batch_id}.json
单次结果读取：reports/{test_run_id}/result.json

batch_id 格式建议：{project_name}_{yyyymmdd_HHMMSS} 或自定义标签（如 v1.2-hotfix）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# repo 根目录（src/tools/ 上两级）
_REPO_ROOT = Path(__file__).parent.parent.parent
_REPORTS_DIR = _REPO_ROOT / "reports"
_BATCHES_DIR = _REPORTS_DIR / "batches"


def main() -> None:
    parser = argparse.ArgumentParser(description="将测试结果追加到批次摘要文件")
    parser.add_argument("--batch-id", required=True, help="批次标识，如 市场洞察_20260501 或 v1.2")
    parser.add_argument("--test-run-id", required=True, help="本次运行的 test_run_id")
    parser.add_argument("--project-name", default="", help="项目名称（可选，写入批次元信息）")
    parser.add_argument("--agent-version", default="", help="Agent 版本标签（可选，如 v1.2）")
    args = parser.parse_args()

    # --- 读取 result.json ---
    result_path = _REPORTS_DIR / args.test_run_id / "result.json"
    if not result_path.exists():
        _exit_error(f"result.json 不存在：{result_path}\n请先完成 Mode C 评估")

    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as e:
        _exit_error(f"解析 result.json 失败：{e}")

    # --- 读取（或初始化）批次文件 ---
    _BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    batch_path = _BATCHES_DIR / f"{args.batch_id}.json"

    if batch_path.exists():
        try:
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
        except Exception as e:
            _exit_error(f"解析批次文件失败：{e}")
    else:
        # 新建批次
        batch = {
            "batch_id": args.batch_id,
            "project_name": args.project_name or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "agent_version": args.agent_version or "",
            "runs": [],
            "summary": {},
        }

    # 可选字段更新（仅在初始值为空且本次提供时更新）
    if args.project_name and not batch.get("project_name"):
        batch["project_name"] = args.project_name
    if args.agent_version and not batch.get("agent_version"):
        batch["agent_version"] = args.agent_version

    # --- 检查是否已存在该 test_run_id（去重）---
    existing_ids = {r.get("test_run_id") for r in batch.get("runs") or []}
    if args.test_run_id in existing_ids:
        # 更新已有条目（重跑场景）
        batch["runs"] = [
            r for r in batch["runs"] if r.get("test_run_id") != args.test_run_id
        ]

    # --- 构造 run 条目 ---
    run_entry: dict = {
        "test_run_id": args.test_run_id,
        "case_id": result.get("case_id", ""),
        "title": result.get("title", ""),
        "passed": result.get("passed"),
        "score": result.get("score"),
        "final_verdict": result.get("final_verdict", ""),
    }
    # 保留 calls_assertion_ok / missing_tools（可选）
    if "calls_assertion_ok" in result:
        run_entry["calls_assertion_ok"] = result["calls_assertion_ok"]
    if result.get("missing_tools"):
        run_entry["missing_tools"] = result["missing_tools"]

    batch["runs"].append(run_entry)

    # --- 重新计算 summary ---
    batch["summary"] = _compute_summary(batch["runs"])
    batch["updated_at"] = datetime.now(timezone.utc).isoformat()

    # --- 写入批次文件 ---
    batch_path.write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- 输出结果 ---
    summary = batch["summary"]
    print(json.dumps({
        "ok": True,
        "batch_id": args.batch_id,
        "batch_path": str(batch_path),
        "run_added": run_entry,
        "summary": summary,
    }, ensure_ascii=False))


def _compute_summary(runs: list[dict]) -> dict:
    """根据 runs 列表重新计算通过率和平均分。"""
    total = len(runs)
    if total == 0:
        return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0, "avg_score": None}

    passed_runs = [r for r in runs if r.get("passed") is True]
    failed_runs = [r for r in runs if r.get("passed") is False]
    scores = [r["score"] for r in runs if isinstance(r.get("score"), (int, float))]

    return {
        "total": total,
        "passed": len(passed_runs),
        "failed": len(failed_runs),
        "pass_rate": round(len(passed_runs) / total, 4),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
    }


def _exit_error(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
