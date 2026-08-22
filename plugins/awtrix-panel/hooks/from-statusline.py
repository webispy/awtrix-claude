#!/usr/bin/env python3
"""Feed the panel the numbers only a statusline command is given.

Context usage as Claude Code itself computes it, the 5-hour and 7-day quota, and the running cost
never reach a hook - they are handed to the statusline, and Claude Code allows one of those. So
this is not a hook: it is a filter to put in front of whatever already owns statusLine.

    json=$(cat)
    printf '%s' "$json" | python3 .../from-statusline.py 2>/dev/null || :
    printf '%s' "$json" | exec <whatever owned statusLine before>

The `|| :` and the `exec` are the point. This half may fail without taking the HUD down with it,
and nothing of it is left running afterwards.

It writes into the same per-session file the hooks use, so the renderer never learns where a
number came from. That is what keeps this an optional add-on: install it and the quota gauge fills
in, skip it and everything else still works.
"""

from __future__ import annotations

import json
import os
import sys
import time
import fcntl

HOME = os.environ.get("AWTRIX_PANEL_HOME") or os.path.expanduser("~/.local/state/awtrix-panel")
SESSIONS = os.path.join(HOME, "sessions")


def session_key(doc: dict) -> str:
    """The statusline payload carries no session id, but the transcript's filename is one - the
    stem matches the sessionId the transcript's own records report."""
    path = doc.get("transcript_path") or ""
    stem = os.path.basename(str(path))
    if stem.endswith(".jsonl"):
        stem = stem[:-6]
    stem = "".join(c for c in stem if c.isalnum() or c in "-_")[:64]
    return stem or "default"


def pct(value) -> int | None:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return None


def merge(path: str, updates: dict) -> None:
    with open(path + ".lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
        except FileNotFoundError:
            # SessionEnd may have removed it after main()'s fast-path existence check but before
            # this lock was acquired. A statusline sample must never resurrect a closed session.
            return
        except Exception:
            loaded = {}
        current = loaded if isinstance(loaded, dict) else {}
        current.update(updates)
        # Deliberately not touching `updated`: this runs on every statusline render, and refreshing
        # the timestamp would keep a finished session alive on the panel forever.
        current.setdefault("updated", time.time())
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f)
        os.replace(tmp, path)


def main() -> int:
    try:
        doc = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(doc, dict):
        return 0

    ctx = doc.get("context_window") or {}
    limits = doc.get("rate_limits") or {}
    cost = doc.get("cost") or {}
    five = (limits.get("five_hour") or {}) if isinstance(limits, dict) else {}
    seven = (limits.get("seven_day") or {}) if isinstance(limits, dict) else {}

    updates: dict = {}
    if (v := pct(ctx.get("used_percentage"))) is not None:
        updates["context_pct"] = v
    if (v := pct(five.get("used_percentage"))) is not None:
        updates["quota_5h"] = v
    if (v := pct(seven.get("used_percentage"))) is not None:
        updates["quota_7d"] = v
    try:
        if cost.get("total_cost_usd") is not None:
            updates["cost_usd"] = round(float(cost["total_cost_usd"]), 2)
    except (TypeError, ValueError):
        pass
    if not updates:
        return 0

    key = session_key(doc)
    os.makedirs(SESSIONS, mode=0o700, exist_ok=True)
    path = os.path.join(SESSIONS, key + ".json")
    # Only fill in an existing session. A statusline render is not evidence that a session is
    # live - the hooks decide that - and inventing a file here would put a panel up for a window
    # that had already been closed.
    if not os.path.exists(path):
        return 0
    merge(path, updates)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
