#!/usr/bin/env python3
"""Exercise the shared Claude/Codex hook collector without starting the renderer."""

import json
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "hooks", "state.py")
STATUSLINE = os.path.join(HERE, "hooks", "from-statusline.py")


def run(home: str, event: str, agent: str, payload: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["AWTRIX_PANEL_HOME"] = home
    env["AWTRIX_PANEL_NO_SPAWN"] = "1"
    return subprocess.run(
        [sys.executable, STATE, event, agent],
        input=json.dumps(payload), text=True, capture_output=True, env=env, check=False,
    )


with tempfile.TemporaryDirectory() as home:
    payload = {"session_id": "thr_codex_test", "transcript_path": "/private/codex.jsonl"}
    started = run(home, "SessionStart", "codex", payload)
    path = os.path.join(home, "sessions", "thr_codex_test.json")
    with open(path, encoding="utf-8") as f:
        record = json.load(f)
    assert started.returncode == 0 and started.stdout == ""
    assert record["agent"] == "codex" and record["status"] == "idle"

    prompt = run(home, "UserPromptSubmit", "codex", payload)
    with open(path, encoding="utf-8") as f:
        record = json.load(f)
    assert prompt.returncode == 0 and record["status"] == "busy" and record["busy_since"]

    stopped = run(home, "Stop", "codex", payload)
    assert stopped.returncode == 0 and json.loads(stopped.stdout) == {}

    subagent = run(home, "SubagentStop", "codex", payload)
    assert subagent.returncode == 0 and json.loads(subagent.stdout) == {}

    ended = run(home, "SessionEnd", "codex", payload)
    assert ended.returncode == 0 and not os.path.exists(path)

    # A late statusline process may pass its first existence check before SessionEnd and acquire
    # the shared lock afterwards. The merge itself must not recreate the removed session.
    spec = importlib.util.spec_from_file_location("awtrix_statusline", STATUSLINE)
    statusline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(statusline)
    statusline.merge(path, {"context_pct": 50})
    assert not os.path.exists(path)

    claude = run(home, "StopFailure", "claude", {"session_id": "claude-test"})
    with open(os.path.join(home, "sessions", "claude-test.json"), encoding="utf-8") as f:
        record = json.load(f)
    assert claude.returncode == 0 and claude.stdout == ""
    assert record["agent"] == "claude" and record["status"] == "error"

print("state: Claude and Codex lifecycle records and hook outputs check out.")
