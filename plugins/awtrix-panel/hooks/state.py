#!/usr/bin/env python3
"""Record one coding-agent event into the panel's state file.

This runs inside a hook, so it is written to be boring: standard library only, no serial port, no
network, and every failure swallowed. A hook that raises or blocks costs the user their session,
and nothing here is worth that. The renderer is the only process that talks to the panel.

    state.py <event> [agent]

The event name comes from argv rather than from the payload, so the wiring in hooks.json is the
single place that has to be right.
"""

from __future__ import annotations

import json
import os
import sys
import time
import fcntl

# One file per session, so several Claude Code or Codex windows can share a panel and the renderer can
# aggregate them. The file is a merge target: hooks own the status fields, the optional statusline
# wrapper owns the context and quota fields, and neither clobbers the other.
HOME = os.environ.get("AWTRIX_PANEL_HOME") or os.path.expanduser("~/.local/state/awtrix-panel")
SESSIONS = os.path.join(HOME, "sessions")

# Both supported hook APIs use snake_case today; accept camelCase as a compatibility fallback.
ID_KEYS = ("session_id", "sessionId")
TOOL_KEYS = ("tool_name", "toolName", "tool")

# Events that mean somebody is using this session, and so that the panel should be alive. Stop is
# in here too: a turn ending is the moment the display has something new to say.
WAKES_RENDERER = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "Stop", "StopFailure"
)

STATUS_FOR = {
    "SessionStart": "idle",
    "UserPromptSubmit": "busy",
    "PreToolUse": "busy",
    "PostToolUse": "busy",
    "PostToolUseFailure": "busy",
    "PermissionRequest": "permission",
    "Stop": "idle",
    # A turn that ended badly is worth a different face than one that simply ended.
    "StopFailure": "error",
    "PostToolUseFailure": "error",
    "PreCompact": "busy",
    "PostCompact": "busy",
    "TeammateIdle": "idle",
}


def read_payload() -> dict:
    """Hook payloads arrive as JSON on stdin. A missing or malformed one is not fatal."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    try:
        doc = json.loads(raw)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def first(doc: dict, keys, default=None):
    for k in keys:
        v = doc.get(k)
        if v:
            return v
    return default


def merge(path: str, updates: dict, deltas: dict | None = None) -> None:
    """Merge one record without losing a concurrent hook or statusline update."""
    with open(path + ".lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = {}
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    current = loaded
        except Exception:
            pass
        for key, delta in (deltas or {}).items():
            current[key] = max(0, int(current.get(key) or 0) + delta)
        current.update(updates)
        current["updated"] = time.time()
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f)
        os.replace(tmp, path)


def remove(path: str) -> None:
    """Remove a session without racing a final statusline or hook merge."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path + ".lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            os.unlink(path)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else ""
    agent = argv[2].lower() if len(argv) > 2 else "claude"
    if agent not in ("claude", "codex"):
        agent = "unknown"
    payload = read_payload()

    session = first(payload, ID_KEYS, "default")
    # Whatever arrives here ends up in a filename, so keep it to something a filename can hold.
    session = "".join(c for c in str(session) if c.isalnum() or c in "-_")[:64] or "default"

    # A session that has gone is not a session with a status, so drop its file outright. That is the
    # whole of it: the renderer re-reads the directory every second, finds one fewer, and the row of
    # marks shrinks. Without it the file sat until the TTL swept it - five minutes of the panel
    # counting a window that had been closed. Only act on a payload that named a session, or a
    # malformed one would take out the fallback file belonging to somebody else.
    if event == "SessionEnd":
        if first(payload, ID_KEYS, "") :
            remove(os.path.join(SESSIONS, session + ".json"))
        return 0

    updates: dict = {"session_id": session, "event": event, "agent": agent}
    if event in STATUS_FOR:
        updates["status"] = STATUS_FOR[event]
    # When the work started, so the panel can say how long it has been going. Only a prompt starts
    # the clock; a tool call in the middle of a turn must not restart it.
    if event == "UserPromptSubmit":
        updates["busy_since"] = time.time()
    elif event in ("Stop", "StopFailure"):
        updates["busy_since"] = None
    for key, field in (("transcript_path", "transcript"), ("cwd", "cwd")):
        if payload.get(key):
            updates[field] = payload[key]

    # The tool name is only interesting while a tool is running.
    if event == "PreToolUse":
        updates["tool"] = first(payload, TOOL_KEYS, "") or ""
    elif event in ("PostToolUse", "PostToolUseFailure", "Stop", "StopFailure"):
        updates["tool"] = ""


    # Subagents come and go in pairs; the renderer shows the count, so track it rather than a flag.
    deltas = {}
    if event in ("SubagentStart", "SubagentStop"):
        deltas["agents"] = 1 if event == "SubagentStart" else -1
    if event == "PreCompact":
        updates["compacting"] = True
        deltas["compactions"] = 1
    elif event == "PostCompact":
        updates["compacting"] = False

    os.makedirs(SESSIONS, mode=0o700, exist_ok=True)
    merge(os.path.join(SESSIONS, session + ".json"), updates, deltas)

    # The renderer ends itself when every session has expired, and it can also be killed or crash.
    # A session that is already open never sees SessionStart again, so waking it only there left
    # such a session with no way to get the panel back at all. Any sign of activity will do.
    #
    # AWTRIX_PANEL_NO_SPAWN is for exercising this collector on its own. A separate
    # AWTRIX_PANEL_HOME is not a sandbox: it gets its own socket, but there is one serial port and a
    # spawned server would take it.
    if event in WAKES_RENDERER and not os.environ.get("AWTRIX_PANEL_NO_SPAWN"):
        if not renderer_current():
            spawn_renderer()
    return 0


def _code_mtime() -> float:
    # realpath, matching the renderer's own reckoning: a locally installed plugin is reached
    # through a symlink, and the two must agree on which file they are timing.
    here = os.path.dirname(os.path.realpath(__file__))
    best = 0.0
    for rel in ("../renderer.py", "../claudlet.py", "../codexmark.py", "../codexusage.py",
                "../panelconfig.py"):
        try:
            best = max(best, os.path.getmtime(os.path.normpath(os.path.join(here, rel))))
        except OSError:
            pass
    return best


def renderer_current() -> bool:
    """True when a renderer is running *and* it is running this code.

    Liveness alone was not enough. A renderer holds its pidfile for as long as a session lasts, so
    an edited plugin - or a `plugin update` - never reached the sessions that were already open:
    the takeover logic existed in the renderer but nothing ever spawned the newer process that
    would trigger it. Reading a pid and two mtimes is cheap enough to do on every prompt.
    """
    try:
        with open(os.path.join(HOME, "renderer.pid"), encoding="utf-8") as f:
            pid_s, _, stamp_s = f.read().strip().partition(" ")
            pid = int(pid_s)
            stamp = float(stamp_s or 0)
        os.kill(pid, 0)
    except Exception:
        return False
    return _code_mtime() <= stamp + 1.0


def spawn_renderer() -> None:
    import subprocess

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "renderer.py")
    log = os.path.join(HOME, "renderer.log")
    try:
        with open(log, "ab") as sink:
            subprocess.Popen(
                [sys.executable, os.path.normpath(script)],
                stdin=subprocess.DEVNULL, stdout=sink, stderr=sink,
                start_new_session=True, close_fds=True,
            )
    except Exception:
        pass


def codex_requires_json(argv: list[str]) -> bool:
    """Codex Stop hooks require valid JSON on a successful command hook."""
    return len(argv) > 2 and argv[2].lower() == "codex" and argv[1] in ("Stop", "SubagentStop")


if __name__ == "__main__":
    code = 0
    try:
        code = main(sys.argv)
    except Exception:
        # A hook that fails must still exit 0. The panel going stale is a far smaller problem than
        # an error surfacing in somebody's session.
        code = 0
    if codex_requires_json(sys.argv):
        print("{}")
    sys.exit(code)
