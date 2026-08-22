#!/usr/bin/env python3
"""Small, reloadable display configuration for the 32x8 layout."""

from __future__ import annotations

import json
import os

PATH = os.environ.get("AWTRIX_PANEL_CONFIG") or os.path.expanduser(
    "~/.config/awtrix-panel/config.json"
)

DEFAULT = {
    "symbol": "auto",
    "gauges": ["quota_primary", "context"],
    "labels": [
        "context",
        "quota_primary",
        "quota_secondary",
        "subagents",
        "tokens_total",
    ],
    "busy_label": "elapsed",
}
SYMBOLS = {"auto", "claude", "codex", "none"}
METRICS = {
    "context",
    "context_remaining",
    "quota_primary",
    "quota_secondary",
    "quota_primary_reset",
    "quota_secondary_reset",
    "elapsed",
    "sessions",
    "subagents",
    "tokens_context",
    "tokens_last",
    "tokens_input",
    "tokens_cached",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
    "credits",
    "model",
    "reasoning",
    "provider",
    "origin",
    "plan",
    "codex_version",
    "tool",
    "compactions",
    "cost",
}


def _display(value: object, base: dict | None = None) -> dict:
    out = dict(base or DEFAULT)
    if not isinstance(value, dict):
        return out
    if value.get("symbol") in SYMBOLS:
        out["symbol"] = value["symbol"]
    gauges = value.get("gauges")
    if isinstance(gauges, list):
        out["gauges"] = [name if name in METRICS else None for name in gauges[:2]]
        out["gauges"] += [None] * (2 - len(out["gauges"]))
    labels = value.get("labels")
    if isinstance(labels, list):
        out["labels"] = [name for name in labels if name in METRICS]
    busy = value.get("busy_label")
    if busy is None or busy in METRICS:
        out["busy_label"] = busy
    return out


def load(path: str | None = None) -> dict:
    """Load defaults, then global display settings, then per-agent overrides."""
    try:
        with open(path or PATH, encoding="utf-8") as stream:
            doc = json.load(stream)
    except Exception:
        doc = {}
    global_display = _display(doc.get("display") if isinstance(doc, dict) else None)
    agents = doc.get("agents") if isinstance(doc, dict) else None
    by_agent = {}
    if isinstance(agents, dict):
        for agent in ("claude", "codex"):
            by_agent[agent] = _display(agents.get(agent), global_display)
    return {"display": global_display, "agents": by_agent}


def for_agent(config: dict, agent: str) -> dict:
    return (config.get("agents") or {}).get(agent) or config.get("display") or dict(DEFAULT)
