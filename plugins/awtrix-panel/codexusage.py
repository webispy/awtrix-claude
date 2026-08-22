#!/usr/bin/env python3
"""Read numeric Codex session telemetry without retaining conversation content.

Codex hooks describe lifecycle but not usage. The local rollout contains compact ``token_count``
events beside the conversation records. This reader only decodes those events plus the small
session and turn metadata records; prompt, response and tool payloads are never parsed or copied.

The rollout schema is an implementation detail rather than a plugin API, so every field is
optional and unknown shapes quietly produce an empty result.
"""

from __future__ import annotations

import glob
import json
import os
import re

CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
_PATHS: dict[str, str | None] = {}
_CACHE: dict[str, dict] = {}

TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
TURN_KEYS = (
    "model",
    "effort",
    "summary",
    "personality",
    "approval_policy",
    "approvals_reviewer",
    "realtime_active",
)
META_KEYS = ("cli_version", "originator", "source", "thread_source", "model_provider")
TOOL_NAME = re.compile(rb'"name":"([A-Za-z0-9_.:-]{1,64})"')


def _safe_session(session_id: object) -> str:
    return "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_")[:64]


def rollout_path(session_id: object, transcript: object = None) -> str | None:
    """Find the rollout named by a hook payload or by its session id."""
    session = _safe_session(session_id)
    if not session:
        return None
    given = os.path.realpath(str(transcript or ""))
    if given and os.path.isfile(given) and session in os.path.basename(given):
        return given
    cached = _PATHS.get(session)
    if cached and os.path.isfile(cached):
        return cached
    pattern = os.path.join(CODEX_HOME, "sessions", "*", "*", "*", f"*{session}.jsonl")
    found = glob.glob(pattern)
    path = max(found, key=os.path.getmtime) if found else None
    _PATHS[session] = path
    return path


def _tokens(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for key in TOKEN_KEYS:
        try:
            out[key] = max(0, int(value.get(key) or 0))
        except (TypeError, ValueError):
            pass
    return out


def _limit(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    out = {}
    for key in ("used_percent", "window_minutes", "resets_at"):
        try:
            number = float(value[key])
            out[key] = int(number) if number.is_integer() else number
        except (KeyError, TypeError, ValueError):
            pass
    return out or None


def _credits(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in ("has_credits", "unlimited", "balance") if key in value}


def _consume(data: dict, raw: bytes) -> None:
    # Most rollout lines contain conversation content and can be skipped without JSON decoding.
    # Tool envelopes are the exception: extract only their constrained name from the raw bytes, so
    # their argument/output payloads are never materialised as Python objects.
    if b'"type":"response_item","payload":{"type":"custom_tool_call"' in raw:
        match = TOOL_NAME.search(raw)
        if match:
            data["last_tool"] = match.group(1).decode("ascii")
            data["tool_active"] = data["last_tool"]
        return
    if b'"type":"response_item","payload":{"type":"custom_tool_call_output"' in raw:
        data["tool_active"] = None
        return
    markers = (
        b'"type":"session_meta","payload":',
        b'"type":"turn_context","payload":',
        b'"type":"event_msg","payload":{"type":"token_count"',
    )
    if not any(marker in raw for marker in markers):
        return
    try:
        item = json.loads(raw)
    except Exception:
        return
    kind = item.get("type")
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return
    if kind == "session_meta":
        for key in META_KEYS:
            if isinstance(payload.get(key), (str, int, float, bool)):
                data[key] = payload[key]
    elif kind == "turn_context":
        for key in TURN_KEYS:
            if isinstance(payload.get(key), (str, int, float, bool)):
                data[key] = payload[key]
    elif kind == "event_msg" and payload.get("type") == "token_count":
        info = payload.get("info")
        if isinstance(info, dict):
            data["usage_last"] = _tokens(info.get("last_token_usage"))
            data["usage_total"] = _tokens(info.get("total_token_usage"))
            try:
                data["context_window"] = max(0, int(info.get("model_context_window") or 0))
            except (TypeError, ValueError):
                pass
        limits = payload.get("rate_limits")
        if isinstance(limits, dict):
            data["rate_limits"] = {
                "limit_id": limits.get("limit_id"),
                "limit_name": limits.get("limit_name"),
                "primary": _limit(limits.get("primary")),
                "secondary": _limit(limits.get("secondary")),
                "credits": _credits(limits.get("credits")),
                "individual_limit": _limit(limits.get("individual_limit")),
                "spend_control_reached": limits.get("spend_control_reached"),
                "plan_type": limits.get("plan_type"),
                "rate_limit_reached_type": limits.get("rate_limit_reached_type"),
            }


def read(session_id: object, transcript: object = None) -> dict:
    """Return the latest safe telemetry for one local Codex session."""
    path = rollout_path(session_id, transcript)
    if not path:
        return {}
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    cached = _CACHE.get(path)
    identity = (stat.st_dev, stat.st_ino)
    if cached is None or cached.get("identity") != identity or stat.st_size < cached.get("offset", 0):
        cached = {"identity": identity, "offset": 0, "data": {}}
        _CACHE[path] = cached
    try:
        with open(path, "rb") as stream:
            stream.seek(cached["offset"])
            for line in stream:
                _consume(cached["data"], line)
            cached["offset"] = stream.tell()
    except OSError:
        return {}
    out = dict(cached["data"])
    out["updated"] = stat.st_mtime
    last = out.get("usage_last") or {}
    window = int(out.get("context_window") or 0)
    used = int(last.get("input_tokens") or 0)
    if window:
        out["context_tokens"] = used
        out["context_pct"] = max(0, min(100, round(used * 100 / window)))
    return out


def reset_cache() -> None:
    """Test helper; a renderer process normally keeps the cache for its whole life."""
    _PATHS.clear()
    _CACHE.clear()
