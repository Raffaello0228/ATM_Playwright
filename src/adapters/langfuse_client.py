"""Langfuse REST API query client for ATM-Playwright."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LangfuseTraceResult:
    trace_id: str
    session_id: str | None
    timestamp: str
    tool_calls: list[str] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    tool_call_failures: dict[str, int] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    tool_latency_ms: float | None = None   # sum of TOOL observation latencies
    llm_latency_ms: float | None = None    # sum of GENERATION observation latencies
    observations: list[dict[str, Any]] = field(default_factory=list)


class LangfuseQueryClient:
    """Query Langfuse REST API using HTTP Basic Auth.

    Args:
        public_key: Langfuse public key (Basic Auth username).
        secret_key: Langfuse secret key (Basic Auth password).
        base_url: Langfuse base URL, e.g. "https://cloud.langfuse.com".
        timeout_s: HTTP timeout in seconds.
    """

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        timeout_s: float = 30.0,
    ) -> None:
        self._auth = (public_key, secret_key)
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def fetch_session_traces(
        self,
        session_id: str,
        min_timestamp_iso: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """GET /api/public/traces for a session, ordered by timestamp asc.

        Fetches all traces in the session (up to limit). Optionally filters
        by fromTimestamp. Returns traces sorted oldest-first so callers can
        iterate in chronological order.
        """
        url = f"{self._base}/api/public/traces"
        params: dict[str, Any] = {
            "sessionId": session_id,
            "limit": limit,
            "orderBy": "timestamp.asc",
        }
        if min_timestamp_iso:
            params["fromTimestamp"] = min_timestamp_iso
        r = self._client.get(url, params=params, auth=self._auth)
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []

    def fetch_recent_traces(
        self,
        session_id: str,
        min_timestamp_iso: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Backward-compat wrapper around fetch_session_traces (desc order)."""
        url = f"{self._base}/api/public/traces"
        params: dict[str, Any] = {
            "sessionId": session_id,
            "fromTimestamp": min_timestamp_iso,
            "limit": limit,
            "orderBy": "timestamp.desc",
        }
        r = self._client.get(url, params=params, auth=self._auth)
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []

    def get_trace_details(self, trace_id: str) -> dict[str, Any]:
        """GET /api/public/traces/{traceId} — returns full trace with observations."""
        url = f"{self._base}/api/public/traces/{trace_id}"
        r = self._client.get(url, auth=self._auth)
        r.raise_for_status()
        return r.json()

    def build_trace_result(self, trace: dict[str, Any]) -> LangfuseTraceResult:
        """Convert a raw Langfuse trace dict into a LangfuseTraceResult."""
        observations: list[dict[str, Any]] = trace.get("observations") or []
        names, counts, failures = _extract_tool_calls_full(observations)
        tool_lat, llm_lat = _extract_latency_breakdown(observations)
        return LangfuseTraceResult(
            trace_id=trace.get("id", ""),
            session_id=trace.get("sessionId"),
            timestamp=trace.get("timestamp", ""),
            tool_calls=names,
            tool_call_counts=counts,
            tool_call_failures=failures,
            input_tokens=_extract_tokens(observations, trace)[0],
            output_tokens=_extract_tokens(observations, trace)[1],
            latency_ms=_extract_latency(trace),
            tool_latency_ms=tool_lat or None,
            llm_latency_ms=llm_lat or None,
            observations=_extract_observation_timeline(observations),
        )

    def build_aggregated_result(
        self, trace_results: list[LangfuseTraceResult]
    ) -> dict[str, Any]:
        """Aggregate multiple per-trace results into a single session-level summary.

        - tool_calls: ordered list, preserving intra-trace order, deduped globally
        - assistant_text: taken from the last trace
        - latency_ms: summed across all traces
        - tokens: summed across all traces
        - traces: per-trace breakdown list
        """
        seen_tools: set[str] = set()
        all_tool_calls: list[str] = []
        total_input = 0
        total_output = 0
        total_latency = 0.0
        total_tool_lat = 0.0
        total_llm_lat = 0.0
        total_counts: dict[str, int] = {}
        total_failures: dict[str, int] = {}

        per_trace = []
        for r in trace_results:
            for tc in r.tool_calls:
                if tc not in seen_tools:
                    seen_tools.add(tc)
                    all_tool_calls.append(tc)
            total_input += r.input_tokens or 0
            total_output += r.output_tokens or 0
            total_latency += r.latency_ms or 0.0
            total_tool_lat += r.tool_latency_ms or 0.0
            total_llm_lat += r.llm_latency_ms or 0.0
            for name, cnt in r.tool_call_counts.items():
                total_counts[name] = total_counts.get(name, 0) + cnt
            for name, cnt in r.tool_call_failures.items():
                total_failures[name] = total_failures.get(name, 0) + cnt
            per_trace.append(
                {
                    "trace_id": r.trace_id,
                    "timestamp": r.timestamp,
                    "tool_calls": r.tool_calls,
                    "tool_call_counts": r.tool_call_counts,
                    "tool_call_failures": r.tool_call_failures,
                    "latency_ms": r.latency_ms,
                    "tool_latency_ms": r.tool_latency_ms,
                    "llm_latency_ms": r.llm_latency_ms,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "observations": r.observations,
                }
            )

        return {
            "found": True,
            "traces_count": len(trace_results),
            "tool_calls": all_tool_calls,
            "tool_call_counts": total_counts,
            "tool_call_failures": total_failures,
            "latency_ms": round(total_latency, 1) or None,
            "tool_latency_ms": round(total_tool_lat, 1) or None,
            "llm_latency_ms": round(total_llm_lat, 1) or None,
            "input_tokens": total_input or None,
            "output_tokens": total_output or None,
            "traces": per_trace,
        }

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Private extraction helpers
# ---------------------------------------------------------------------------

def _is_failed_obs(obs: dict[str, Any]) -> bool:
    """Return True if a Langfuse observation indicates an error/failure."""
    return (obs.get("level") or "").upper() == "ERROR"


def _extract_tool_calls_full(
    observations: list[dict[str, Any]],
) -> tuple[list[str], dict[str, int], dict[str, int]]:
    """Extract tool calls from Langfuse observations.

    Returns:
        names: ordered deduplicated logical tool names
        counts: {logical_name: total invocation count} (not deduplicated)
        failures: {logical_name: error count}

    Strategy:
    1. TOOL type observations (explicit tool-call records) — counts + failures tracked.
       - If the tool is "bash" and the command matches `npx openskills <action>
         <skill-name>`, the skill name is used instead of "bash".
    2. SPAN observations whose name doesn't look like an LLM generation span — counts + failures tracked.
    3. Tool call names embedded in GENERATION observation output — dedup list only
       (no per-call status available).
    """
    _LLM_KEYWORDS = ("generation", "llm", "model", "chat", "completion")
    seen: set[str] = set()
    result: list[str] = []
    counts: dict[str, int] = {}
    failures: dict[str, int] = {}

    def _record(obs: dict[str, Any], logical: str) -> None:
        if logical not in seen:
            seen.add(logical)
            result.append(logical)
        counts[logical] = counts.get(logical, 0) + 1
        if _is_failed_obs(obs):
            failures[logical] = failures.get(logical, 0) + 1

    # Strategy 1: TOOL type observations (highest fidelity)
    for obs in observations:
        obs_type = (obs.get("type") or "").upper()
        name = (obs.get("name") or "").strip()
        if not name or obs_type != "TOOL":
            continue
        logical = _skill_name_from_bash(obs) or name
        _record(obs, logical)

    # Strategy 2: SPAN observations (non-LLM)
    for obs in observations:
        obs_type = (obs.get("type") or "").upper()
        name = (obs.get("name") or "").strip()
        if not name or obs_type != "SPAN":
            continue
        lower = name.lower()
        if any(k in lower for k in _LLM_KEYWORDS):
            continue
        logical = _skill_name_from_bash(obs) or name
        _record(obs, logical)

    # Strategy 3: tool_calls embedded in GENERATION output (dedup list only)
    for obs in observations:
        if (obs.get("type") or "").upper() != "GENERATION":
            continue
        output = obs.get("output") or {}
        if not isinstance(output, dict):
            continue
        tc_list = output.get("tool_calls") or output.get("toolCalls") or []
        if not isinstance(tc_list, list):
            continue
        for tc in tc_list:
            n: str | None = None
            if isinstance(tc, dict):
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
                n = ((fn or {}).get("name") or tc.get("name") or tc.get("tool_name"))
            if isinstance(n, str) and n and n not in seen:
                seen.add(n)
                result.append(n)

    return result, counts, failures



def _extract_tokens(
    observations: list[dict[str, Any]],
    trace: dict[str, Any],
) -> tuple[int | None, int | None]:
    """Sum input/output tokens from GENERATION observations or trace-level usage."""
    input_total = 0
    output_total = 0
    found = False
    for obs in observations:
        if (obs.get("type") or "").upper() != "GENERATION":
            continue
        usage = obs.get("usage") or {}
        inp = usage.get("input") or usage.get("promptTokens") or usage.get("input_tokens") or 0
        out = usage.get("output") or usage.get("completionTokens") or usage.get("output_tokens") or 0
        try:
            input_total += int(inp)
            output_total += int(out)
            found = True
        except (TypeError, ValueError):
            pass
    if found:
        return (input_total or None), (output_total or None)
    usage = trace.get("usage") or {}
    return (
        _to_int(usage.get("input") or usage.get("promptTokens")),
        _to_int(usage.get("output") or usage.get("completionTokens")),
    )


def _extract_latency(trace: dict[str, Any]) -> float | None:
    """Derive latency_ms from trace.latency (seconds) field."""
    latency_s = trace.get("latency")
    if latency_s is not None:
        try:
            return round(float(latency_s) * 1000, 1)
        except (TypeError, ValueError):
            pass
    return None


def _extract_latency_breakdown(
    observations: list[dict[str, Any]],
) -> tuple[float, float]:
    """Sum TOOL and GENERATION observation latencies separately.

    Langfuse observation `latency` field is in seconds; converted to ms here.

    Returns:
        (tool_latency_ms, llm_latency_ms)
    """
    tool_ms = 0.0
    llm_ms = 0.0
    for obs in observations:
        raw_lat = obs.get("latency")
        if raw_lat is None:
            continue
        try:
            ms = float(raw_lat) * 1000
        except (TypeError, ValueError):
            continue
        obs_type = (obs.get("type") or "").upper()
        if obs_type == "TOOL":
            tool_ms += ms
        elif obs_type == "GENERATION":
            llm_ms += ms
    return round(tool_ms, 1), round(llm_ms, 1)


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _skill_name_from_bash(obs: dict[str, Any]) -> str | None:
    """If this observation is a bash call invoking a skill via npx openskills,
    return the skill name. Otherwise return None.

    Matches the pattern: npx openskills <action> <skill-name>
    Example input: {"command": "npx openskills read universal-writer"}
    Returns: "universal-writer"
    """
    import re

    name = (obs.get("name") or "").lower()
    if "bash" not in name:
        return None

    raw_input = obs.get("input")
    command = ""
    if isinstance(raw_input, dict):
        command = raw_input.get("command") or ""
    elif isinstance(raw_input, str):
        command = raw_input

    m = re.search(r"npx\s+openskills\s+\S+\s+(\S+)", command)
    return m.group(1) if m else None


def _extract_observation_timeline(
    observations: list[dict[str, Any]],
    input_preview_chars: int = 300,
) -> list[dict[str, Any]]:
    """Build a lightweight observation timeline.

    For GENERATION observations, input/output bodies are omitted (can be very
    large). For TOOL and SPAN observations, a truncated preview of `input` is
    included so callers can inspect tool arguments (e.g. to identify whether a
    bash call is invoking a skill vs running a shell command).
    """
    result = []
    for obs in observations:
        obs_type = (obs.get("type") or "").upper()
        raw_lat = obs.get("latency")
        entry: dict[str, Any] = {
            "type": obs.get("type"),
            "name": obs.get("name"),
            "model": obs.get("model"),
            "latency_ms": round(float(raw_lat) * 1000, 1) if raw_lat is not None else None,
            "usage": obs.get("usage") or None,
            "status": obs.get("statusMessage") or obs.get("status"),
        }
        # Include truncated input for TOOL/SPAN so callers can inspect arguments
        if obs_type in ("TOOL", "SPAN"):
            raw_input = obs.get("input")
            if raw_input is not None:
                if isinstance(raw_input, str):
                    preview = raw_input[:input_preview_chars]
                else:
                    try:
                        import json as _json
                        preview = _json.dumps(raw_input, ensure_ascii=False)[:input_preview_chars]
                    except Exception:
                        preview = str(raw_input)[:input_preview_chars]
                entry["input_preview"] = preview
        result.append(entry)
    return result
