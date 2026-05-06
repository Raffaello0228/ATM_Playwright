"""CLI tool for managing ATM-Playwright test results.

Subcommands:
  query   — filter/search result runs
  compare — compare the same case across multiple runs
  archive — move/zip/delete old run directories
  summary — aggregated pass-rate and score overview

Run from repo root:
  .venv/bin/python src/tools/manage_results.py <subcommand> [options]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("reports")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _parse_run_dir(run_dir: Path) -> dict[str, Any] | None:
    """Parse a run directory and return a flat record, or None if not a valid run."""
    if not run_dir.is_dir():
        return None
    if run_dir.name == "batches" or run_dir.name == "archive":
        return None
    result_file = run_dir / "result.json"
    if not result_file.exists():
        return None

    parts = run_dir.name.rsplit("_", 2)
    if len(parts) != 3:
        return None
    case_id_part, date_part, time_part = parts
    try:
        run_date = date(int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8]))
    except (ValueError, IndexError):
        return None

    with open(result_file, encoding="utf-8") as f:
        data = json.load(f)

    return {
        "test_run_id": run_dir.name,
        "case_id": data.get("case_id", case_id_part),
        "date": run_date,
        "date_str": str(run_date),
        "passed": bool(data.get("passed")),
        "score": float(data.get("score") or 0.0),
        "missing_tools": data.get("missing_tools") or [],
        "calls_assertion_ok": bool(data.get("calls_assertion_ok")),
    }


def load_all_runs(reports_dir: Path = REPORTS_DIR) -> list[dict[str, Any]]:
    """Load all valid run records from reports/, sorted oldest first."""
    records = []
    for d in reports_dir.iterdir():
        rec = _parse_run_dir(d)
        if rec is not None:
            records.append(rec)
    records.sort(key=lambda r: r["test_run_id"])
    return records


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _yn(v: bool) -> str:
    return "Y" if v else "N"


def _col(value: Any, width: int) -> str:
    return str(value).ljust(width)


def _print_table(headers: list[str], widths: list[int], rows: list[list[Any]]) -> None:
    header_line = "  ".join(_col(h, w) for h, w in zip(headers, widths))
    separator = "  ".join("-" * w for w in widths)
    print(header_line)
    print(separator)
    for row in rows:
        print("  ".join(_col(v, w) for v, w in zip(row, widths)))


# ---------------------------------------------------------------------------
# Subcommand: query
# ---------------------------------------------------------------------------

def cmd_query(args: argparse.Namespace) -> None:
    runs = load_all_runs()

    if args.case_id:
        runs = [r for r in runs if r["case_id"] == args.case_id]
    if args.passed:
        runs = [r for r in runs if r["passed"]]
    if args.failed:
        runs = [r for r in runs if not r["passed"]]
    if args.date_from:
        cutoff = date.fromisoformat(args.date_from)
        runs = [r for r in runs if r["date"] >= cutoff]
    if args.date_to:
        cutoff = date.fromisoformat(args.date_to)
        runs = [r for r in runs if r["date"] <= cutoff]
    if args.score_min is not None:
        runs = [r for r in runs if r["score"] >= args.score_min]
    if args.score_max is not None:
        runs = [r for r in runs if r["score"] <= args.score_max]

    if args.json:
        print(json.dumps(runs, default=str, ensure_ascii=False, indent=2))
        return

    if not runs:
        print("(no results)")
        return

    headers = ["test_run_id", "case_id", "date", "passed", "score"]
    widths = [36, 12, 12, 7, 6]
    rows = [
        [r["test_run_id"], r["case_id"], r["date_str"], _yn(r["passed"]), f"{r['score']:.1f}"]
        for r in runs
    ]
    _print_table(headers, widths, rows)
    print(f"\n{len(runs)} run(s) found.")


# ---------------------------------------------------------------------------
# Subcommand: compare
# ---------------------------------------------------------------------------

def cmd_compare(args: argparse.Namespace) -> None:
    runs = load_all_runs()
    runs = [r for r in runs if r["case_id"] == args.case_id]

    if not runs:
        print(f"No runs found for case_id: {args.case_id}")
        sys.exit(1)

    if args.last:
        runs = runs[-args.last:]

    print(f"case_id: {args.case_id}  ({len(runs)} run(s))\n")

    headers = ["date", "test_run_id", "passed", "score", "missing_tools"]
    widths = [12, 36, 7, 6, 30]
    rows = [
        [
            r["date_str"],
            r["test_run_id"],
            _yn(r["passed"]),
            f"{r['score']:.1f}",
            ", ".join(r["missing_tools"]) if r["missing_tools"] else "-",
        ]
        for r in runs
    ]
    _print_table(headers, widths, rows)

    if len(runs) >= 2:
        first_score = runs[0]["score"]
        last_score = runs[-1]["score"]
        trend = "↑" if last_score > first_score else ("↓" if last_score < first_score else "→")

        consecutive = 0
        for r in reversed(runs):
            if r["passed"]:
                consecutive += 1
            else:
                break

        print(
            f"\n趋势: 得分 {first_score:.1f} → {last_score:.1f} ({trend})"
            f"  连续通过: {consecutive} 次"
        )


# ---------------------------------------------------------------------------
# Subcommand: summary
# ---------------------------------------------------------------------------

def cmd_summary(args: argparse.Namespace) -> None:
    runs = load_all_runs()

    if args.case_id:
        runs = [r for r in runs if r["case_id"] == args.case_id]

    if not runs:
        print("(no results)")
        return

    # Aggregate by case_id
    by_case: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        by_case.setdefault(r["case_id"], []).append(r)

    # Build per-case rows
    case_rows = []
    for case_id, case_runs in sorted(by_case.items()):
        n = len(case_runs)
        passed = sum(1 for r in case_runs if r["passed"])
        pass_pct = round(passed / n * 100)
        avg_score = sum(r["score"] for r in case_runs) / n
        last_run = max(r["date_str"] for r in case_runs)
        case_rows.append((case_id, n, passed, pass_pct, avg_score, last_run))

    # Sort by pass% asc, then avg_score asc (worst first by default)
    case_rows.sort(key=lambda x: (x[3], x[4]))

    if args.top:
        case_rows = case_rows[: args.top]

    total_runs = len(runs)
    total_passed = sum(1 for r in runs if r["passed"])
    overall_pass_pct = round(total_passed / total_runs * 100, 1) if total_runs else 0
    overall_avg = sum(r["score"] for r in runs) / total_runs if total_runs else 0

    print(
        f"总计: {total_runs} 次运行  {len(by_case)} 个 case  "
        f"通过率 {overall_pass_pct}%  均分 {overall_avg:.1f}\n"
    )

    headers = ["case_id", "runs", "passed", "pass%", "avg_score", "last_run"]
    widths = [14, 6, 7, 7, 10, 12]
    rows = [
        [cid, n, p, f"{pp}%", f"{avg:.1f}", last]
        for cid, n, p, pp, avg, last in case_rows
    ]
    _print_table(headers, widths, rows)


# ---------------------------------------------------------------------------
# Subcommand: archive
# ---------------------------------------------------------------------------

def cmd_archive(args: argparse.Namespace) -> None:
    today = date.today()
    runs = load_all_runs()

    to_process = [r for r in runs if (today - r["date"]).days > args.older_than]

    if not to_process:
        print(f"No runs older than {args.older_than} days.")
        return

    action = "delete" if args.delete else ("zip" if args.zip else "move")
    print(
        f"{'[DRY RUN] ' if args.dry_run else ''}"
        f"Will {action} {len(to_process)} run(s) older than {args.older_than} days:\n"
    )
    for r in to_process:
        print(f"  {r['test_run_id']}  ({r['date_str']})")

    if args.dry_run:
        print("\n(dry run — no changes made)")
        return

    if args.delete and not args.force:
        print(
            "\nWARNING: --delete permanently removes data. Re-run with --force to confirm."
        )
        sys.exit(1)

    reports_dir = REPORTS_DIR
    archive_dir = reports_dir / "archive"

    if args.zip:
        archive_dir.mkdir(parents=True, exist_ok=True)
        zip_name = archive_dir / f"archive_{today.strftime('%Y%m%d')}.zip"
        with zipfile.ZipFile(zip_name, "a", compression=zipfile.ZIP_DEFLATED) as zf:
            for r in to_process:
                run_path = reports_dir / r["test_run_id"]
                for file in run_path.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(reports_dir))
        print(f"\nArchived to {zip_name}")
        for r in to_process:
            shutil.rmtree(reports_dir / r["test_run_id"])
        print(f"Removed {len(to_process)} original run directories.")

    elif args.delete:
        for r in to_process:
            shutil.rmtree(reports_dir / r["test_run_id"])
        print(f"\nDeleted {len(to_process)} run directories.")

    else:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for r in to_process:
            src = reports_dir / r["test_run_id"]
            dst = archive_dir / r["test_run_id"]
            shutil.move(str(src), str(dst))
        print(f"\nMoved {len(to_process)} run directories to {archive_dir}/")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_results",
        description="Manage ATM-Playwright test results.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- query ---
    p_query = sub.add_parser("query", help="Filter/search run results")
    p_query.add_argument("--case-id", help="Filter by case_id (exact match)")
    group = p_query.add_mutually_exclusive_group()
    group.add_argument("--passed", action="store_true", help="Only passing runs")
    group.add_argument("--failed", action="store_true", help="Only failing runs")
    p_query.add_argument("--date-from", metavar="YYYY-MM-DD", help="Runs on or after this date")
    p_query.add_argument("--date-to", metavar="YYYY-MM-DD", help="Runs on or before this date")
    p_query.add_argument("--score-min", type=float, metavar="N", help="Minimum score")
    p_query.add_argument("--score-max", type=float, metavar="N", help="Maximum score")
    p_query.add_argument("--json", action="store_true", help="Output raw JSON instead of table")

    # --- compare ---
    p_cmp = sub.add_parser("compare", help="Compare a case across multiple runs")
    p_cmp.add_argument("--case-id", required=True, help="case_id to compare")
    p_cmp.add_argument("--last", type=int, metavar="N", help="Show only the N most recent runs")

    # --- summary ---
    p_sum = sub.add_parser("summary", help="Overview of all results aggregated by case")
    p_sum.add_argument("--case-id", help="Restrict to a specific case_id")
    p_sum.add_argument(
        "--top", type=int, metavar="N",
        help="Show only the N lowest-scoring cases (worst first)"
    )

    # --- archive ---
    p_arc = sub.add_parser("archive", help="Archive or delete old run directories")
    p_arc.add_argument(
        "--older-than", type=int, required=True, metavar="DAYS",
        help="Process runs older than this many days"
    )
    p_arc.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    mode_group = p_arc.add_mutually_exclusive_group()
    mode_group.add_argument("--zip", action="store_true", help="Compress into a zip archive")
    mode_group.add_argument(
        "--delete", action="store_true", help="Permanently delete (requires --force)"
    )
    p_arc.add_argument("--force", action="store_true", help="Required with --delete")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "query": cmd_query,
        "compare": cmd_compare,
        "summary": cmd_summary,
        "archive": cmd_archive,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
