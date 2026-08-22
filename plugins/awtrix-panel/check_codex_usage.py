#!/usr/bin/env python3
"""Exercise the rollout telemetry reader with no real Codex session data."""

import json
import os
import tempfile

import codexusage as usage


def line(kind, payload):
    return json.dumps({"timestamp": "2026-08-22T00:00:00Z", "type": kind, "payload": payload},
                      separators=(",", ":")) + "\n"


def token_event(input_tokens, total_tokens, used=31):
    return line("event_msg", {
        "type": "token_count",
        "info": {
            "last_token_usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": input_tokens // 2,
                "output_tokens": 90,
                "reasoning_output_tokens": 30,
                "total_tokens": input_tokens + 120,
            },
            "total_token_usage": {
                "input_tokens": total_tokens - 500,
                "cached_input_tokens": total_tokens // 2,
                "output_tokens": 400,
                "reasoning_output_tokens": 100,
                "total_tokens": total_tokens,
            },
            "model_context_window": 200000,
        },
        "rate_limits": {
            "limit_id": "codex",
            "primary": {"used_percent": used, "window_minutes": 10080, "resets_at": 2000000000},
            "secondary": {"used_percent": 12, "window_minutes": 300, "resets_at": 1900000000},
            "credits": {"has_credits": True, "unlimited": False, "balance": "7"},
            "plan_type": "plus",
        },
    })


with tempfile.TemporaryDirectory() as home:
    session = "codex-test"
    folder = os.path.join(home, "sessions", "2026", "08", "22")
    os.makedirs(folder)
    path = os.path.join(folder, f"rollout-{session}.jsonl")
    usage.CODEX_HOME = home
    usage.reset_cache()
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(line("session_meta", {
            "session_id": session, "cli_version": "0.149.0", "originator": "codex-tui",
            "model_provider": "openai", "base_instructions": "must never be retained",
        }))
        # A conversation line can contain the marker as text; its top-level shape must keep it out.
        stream.write(line("response_item", {"type": "message", "text": '"type":"token_count"'}))
        stream.write(line("turn_context", {
            "model": "gpt-5.6-sol", "effort": "medium", "personality": "pragmatic",
            "cwd": "/private/work",
        }))
        stream.write(line("response_item", {
            "type": "custom_tool_call", "name": "exec", "input": "must never be retained",
        }))
        stream.write(line("response_item", {
            "type": "custom_tool_call_output", "output": "must never be retained",
        }))
        stream.write(token_event(100000, 2500000))

    first = usage.read(session)
    assert first["context_pct"] == 50 and first["context_tokens"] == 100000
    assert first["usage_total"]["total_tokens"] == 2500000
    assert first["usage_last"]["reasoning_output_tokens"] == 30
    assert first["rate_limits"]["primary"]["used_percent"] == 31
    assert first["rate_limits"]["secondary"]["window_minutes"] == 300
    assert first["rate_limits"]["credits"]["balance"] == "7"
    assert first["model"] == "gpt-5.6-sol" and first["effort"] == "medium"
    assert first["last_tool"] == "exec" and first["tool_active"] is None
    assert "base_instructions" not in first and "text" not in first and "cwd" not in first
    assert "input" not in first and "output" not in first

    with open(path, "a", encoding="utf-8") as stream:
        stream.write(token_event(150000, 3000000, used=42))
    second = usage.read(session)
    assert second["context_pct"] == 75
    assert second["usage_total"]["total_tokens"] == 3000000
    assert second["rate_limits"]["primary"]["used_percent"] == 42

    # A replaced/truncated rollout resets the incremental reader rather than retaining old usage.
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(token_event(20000, 50000, used=2))
    third = usage.read(session)
    assert third["context_pct"] == 10 and third["usage_total"]["total_tokens"] == 50000
    assert third["rate_limits"]["primary"]["used_percent"] == 2

print("codex usage: context, token detail, limits, metadata and incremental reads check out.")
