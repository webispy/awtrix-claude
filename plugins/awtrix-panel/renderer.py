#!/usr/bin/env python3
"""Turn the state the hooks recorded into layers on the panel.

This decides *what* to show; pixelwired decides how it reaches the panel. That split is what makes the
animation affordable: the server owns the serial port and streams only the pixels that changed, so
a walk cycle costs about thirty bytes a frame rather than the eight hundred a whole sprite payload
costs as draw commands.

Standard library only, like the daemon's client half. Started by the SessionStart hook and ends
itself once every session has gone quiet, handing the panel back to the clock.

    renderer.py [--once]
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import claudlet  # noqa: E402

HOME = os.environ.get("AWTRIX_PANEL_HOME") or os.path.expanduser("~/.local/state/awtrix-panel")
SESSIONS = os.path.join(HOME, "sessions")
PIDFILE = os.path.join(HOME, "renderer.pid")

# How long a session may go untouched before it stops counting. Fifteen minutes was chosen to sit
# through a long think, but a session file is only refreshed by a hook - so a window left open and
# unused keeps counting for that whole time, and with several of them the panel follows whichever
# was touched last rather than whichever is being used. Five is long enough for any single turn.
TTL = float(os.environ.get("AWTRIX_PANEL_TTL", "300"))
POLL = float(os.environ.get("AWTRIX_PANEL_INTERVAL", "1.0"))
# A hook is not told the size of the context window, so the divisor starts at the common one and
# is corrected by what the transcript actually shows - see window_for().
WINDOW = int(os.environ.get("AWTRIX_PANEL_CONTEXT_WINDOW", "0"))
WINDOW_TIERS = (200_000, 1_000_000)
WALK_FPS = float(os.environ.get("AWTRIX_PANEL_WALK_FPS", "6"))
# The label cycles through its metrics rather than picking one, so a glance eventually sees all of
# them. Dwell is in frames at this rate.
LABEL_FPS = float(os.environ.get("AWTRIX_PANEL_LABEL_FPS", "10"))
LABEL_DWELL = int(os.environ.get("AWTRIX_PANEL_LABEL_DWELL", "18"))

STATE_LOOK = {          # status -> creature expression, and whether it walks
    "busy":       ("idle",  True),
    "permission": ("ask",   False),
    "error":      ("error", False),
    "idle":       ("sleep", False),
}
# Which status wins when several sessions disagree. Being asked for something beats a failure,
# because only one of the two is waiting on you.
STATUS_RANK = {"permission": 3, "error": 2, "busy": 1, "idle": 0}
# One hue per gauge; brightness does the rest. Mixing hues along a bar reads as several colours
# rather than as a gradient, so the level is signalled by which hue, not by a blend.
CONTEXT_HUES = ((85, (255, 60, 45)), (60, (255, 170, 40)), (0, (60, 210, 120)))
QUOTA_HUES = ((85, (220, 90, 255)), (60, (90, 140, 255)), (0, (40, 200, 200)))

# Session marks follow the firmware's own weekday bar: one row tall, a few pixels wide, a pixel of
# gap, dim for the ones that are not today and bright for the one that is (see WeekdayBar.h, which
# draws segments of width 2 or 3 with inactiveColor 0x666666). Borrowing that language means the
# marks read as marks rather than as a decoration nobody chose.
#
# They sit in the bottom-right corner, on the last row, which is where the firmware puts its own
# bar. Both gauges stop at the same column so they read as a pair rather than as two ragged lines,
# and the corner above the marks stays dark to separate them from the bars.
GAUGE_W = 20
DOTS_Y = 7
DOTS_X = 21
DOT_STEP, DOT_W = 3, 2
MAX_DOTS = (32 - DOTS_X + DOT_STEP - DOT_W) // DOT_STEP
STATUS_DOT = {"busy": (255, 176, 0), "permission": (255, 32, 32),
              "error": (255, 120, 90), "idle": (255, 255, 255)}
IDLE_DOT = (0x66, 0x66, 0x66)   # the firmware's own inactive weekday colour
# The clock's own colon pulse, from src/core/apps/ClockText.cpp: a raised cosine over two seconds.
# Matching it means the panel breathes at the rate the rest of the device already does.
PULSE_MS = 2000
# Not all the way to black, which is what the colon does: a dot also encodes how many sessions
# there are, and a lone busy session would leave the row empty at the bottom of every breath.
PULSE_FLOOR = 0.12
# A dot that is not the followed session still shows its own trouble, just quieter.
OTHER_LEVEL = 0.55

STOP = False


def _stop(_sig, _frame):
    global STOP
    STOP = True


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


# ---- the server, and how to reach it -------------------------------------------------


DAEMON = "pixelwired"

# The daemon is its own program now, installed on PATH, with its own state directory and its own
# socket. The plugin used to hunt for a directory inside the firmware checkout and run a script out
# of it; all that is left of that is asking PATH where the command is.
import panelclient as pc  # noqa: E402


_missing_reported = False


def _stale(got: dict) -> bool:
    """True when the running daemon predates the binary it was started from.

    A daemon outlives the upgrade that changed how it composites, so a long session would otherwise
    keep yesterday's one alive for hours.

    The daemon names its own files, because a client that reached it through an installed shim has
    no other way to know what it is running. This looked for `pixelwired.py` and its modules by
    name in the daemon's directory, which was right when the daemon was Python and has found
    nothing at all since it became one compiled binary - a check that always answered "fresh".
    """
    running = float(got.get("code") or 0)
    if not running:
        return False
    newest = 0.0
    for path in got.get("code_files") or ():
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            pass
    return newest > running + 1.0


def _daemon_path() -> str | None:
    """Where `pixelwired` is, or None.

    PATH first, then the usual install locations by hand: a hook does not always inherit the PATH a
    login shell has, and the renderer is started by a hook. That was learned once already, with the
    previous client, and it is cheaper to keep than to rediscover.
    """
    for found in (shutil.which(DAEMON), os.path.expanduser(f"~/.local/bin/{DAEMON}"),
                  f"/usr/local/bin/{DAEMON}", f"/opt/homebrew/bin/{DAEMON}"):
        if found and os.path.exists(found):
            return found
    return None


def _spawn() -> bool:
    exe = _daemon_path()
    if exe is None:
        global _missing_reported
        if not _missing_reported:
            _missing_reported = True
            log(f"{DAEMON} is not installed - see https://github.com/webispy/pixelwire")
        return False
    log(f"starting {DAEMON}")
    try:
        # --managed says this one is ours: it may time out when every session goes quiet, and we
        # may retire it later. A daemon somebody started by hand gets neither done to it.
        os.makedirs(pc.HOME, mode=0o700, exist_ok=True)
        with open(os.path.join(pc.HOME, "pixelwired.log"), "ab") as sink:
            subprocess.Popen([exe, "--managed"], stdin=subprocess.DEVNULL, stdout=sink,
                             stderr=sink, start_new_session=True, close_fds=True)
    except Exception as exc:
        log(f"cannot start {DAEMON}: {exc!r}")
        return False
    for _ in range(40):                     # it has a serial port to open first
        time.sleep(0.25)
        if pc.stat() is not None:
            return True
    log(f"{DAEMON} did not come up - see {os.path.join(pc.HOME, 'pixelwired.log')}")
    return False


def ensure_server() -> bool:
    """Use the daemon that is up, start one when none is. It ends itself when idle, so this has to
    be able to bring it back at any point, not just once."""
    got = pc.stat()
    if got is None:
        return _spawn()
    if not _stale(got):
        return True
    if not got.get("managed"):
        # Somebody started this one themselves. Killing it would take away a panel they are
        # watching, and it is not ours to decide is too old. Say so once and draw on it anyway.
        global _missing_reported
        if not _missing_reported:
            _missing_reported = True
            log(f"the running {DAEMON} predates its code on disk; restart it to pick up changes")
        return True
    log(f"retiring the {DAEMON} we started, which is running older code")
    pc.request({"op": "quit", "retire": True})
    for _ in range(20):
        time.sleep(0.1)
        if pc.stat() is None:
            break
    return _spawn()


# ---- state ---------------------------------------------------------------------------


def context_from_transcript(path: str) -> int | None:
    """Tokens held by the newest assistant turn. Reads the tail; transcripts only grow."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 262144))
            tail = f.read().decode("utf-8", "replace")
    except Exception:
        return None
    for line in reversed(tail.splitlines()):
        try:
            usage = (json.loads(line).get("message") or {}).get("usage")
        except Exception:
            continue
        if isinstance(usage, dict):
            return sum(int(usage.get(k) or 0) for k in
                       ("input_tokens", "cache_creation_input_tokens",
                        "cache_read_input_tokens", "output_tokens"))
    return None


_observed = 0


def window_for(tokens: int | None) -> int:
    """The window, measured rather than guessed.

    An explicit setting wins. Otherwise start at the usual 200k and step up when a turn is seen
    that could not have fitted in it: a model with a bigger window says so by holding more tokens
    than a smaller one could. Without this the gauge on a 1M model reads five times too full, and
    with it nobody has to configure anything.
    """
    global _observed
    if WINDOW:
        return WINDOW
    if tokens:
        _observed = max(_observed, tokens)
    for tier in WINDOW_TIERS:
        if _observed <= tier:
            return tier
    return WINDOW_TIERS[-1]


def collect(now: float) -> dict:
    sessions = []
    for name in (os.listdir(SESSIONS) if os.path.isdir(SESSIONS) else []):
        if not name.endswith(".json"):
            continue
        path = os.path.join(SESSIONS, name)
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        if now - float(rec.get("updated") or 0) > TTL:
            log(f"expire {name}")
            try:
                os.unlink(path)
            except Exception:
                pass
            continue
        # A file the statusline filter keeps fresh but no hook ever wrote to belongs to a session
        # that predates the plugin. Its numbers are real, but it is not a session the panel is
        # following, and counting it makes the display jump between windows.
        if not rec.get("event"):
            continue
        sessions.append(rec)

    if not sessions:
        return {"live": 0}

    # The panel follows one session - the one worked in most recently - because a figure taken
    # across all of them belongs to none of them. Aggregating context with max() showed 89% from a
    # long-running window while the statusline being read said 4%, and both were right.
    primary = max(sessions, key=lambda r: float(r.get("updated") or 0))
    # Dots are ordered by session id, not by recency: an active dot that jumped position whenever
    # another window was touched would be unreadable.
    ordered = sorted(sessions, key=lambda r: str(r.get("session_id") or ""))
    active = ordered.index(primary)

    # Status is the exception: a session blocked on permission is worth interrupting for even when
    # it is not the one in front of you.
    status = primary.get("status")
    loudest = max(sessions, key=lambda r: STATUS_RANK.get(r.get("status"), 0))
    if STATUS_RANK.get(loudest.get("status"), 0) > STATUS_RANK.get(status, 0):
        status = loudest.get("status")
    if status not in STATE_LOOK:
        status = "idle"

    tokens = None
    if primary.get("transcript"):
        tokens = context_from_transcript(primary["transcript"])
    window = window_for(tokens)
    context = primary.get("context_pct")        # the statusline filter, when installed
    if context is None and tokens is not None:
        context = round(tokens * 100 / window)
    if context is not None:
        context = max(0, min(100, int(context)))

    # Quota is per account rather than per session, so it comes from whoever reported it last.
    quota = primary.get("quota_5h")
    if quota is None:
        for rec in sorted(sessions, key=lambda r: -float(r.get("updated") or 0)):
            if rec.get("quota_5h") is not None:
                quota = int(rec["quota_5h"])
                break

    cost = primary.get("cost_usd")
    since = primary.get("busy_since")
    elapsed = None
    if status == "busy" and since:
        elapsed = max(0.0, now - float(since))
    # One status per dot, in dot order, so each session's own state can be drawn rather than the
    # single figure the rest of the panel uses.
    states = [(r.get("status") if r.get("status") in STATE_LOOK else "idle") for r in ordered]
    return {"live": len(sessions), "active": active, "status": status, "states": states,
            "tokens": tokens,
            "context": context, "elapsed": None if elapsed is None else int(elapsed),
            "quota": None if quota is None else int(quota),
            "cost": None if cost is None else float(cost),
            "agents": sum(int(r.get("agents") or 0) for r in sessions)}


# ---- layers --------------------------------------------------------------------------


def _hue(pct: int, table) -> tuple:
    for threshold, rgb in table:
        if pct >= threshold:
            return rgb
    return table[-1][1]


def _at_least_visible(lit: tuple, base: tuple) -> tuple:
    """Lift a colour that would quantise away back to one step above black.

    PULSE_FLOOR is a fraction, and four bits a channel is a coarse grid: 12% of the amber the busy
    state happens to use survives it, 12% of anything below roughly 0x88 does not. That made the
    floor mean "never goes out, as long as the colour is bright enough", which is not a promise
    worth having - the dot stands for a session, and a dark session is a lost one.
    """
    if not any(base) or any(c >> 4 for c in lit):
        return lit
    top = max(lit) or 1
    return tuple(min(255, round(c * 0x10 / top)) for c in lit)


def session_dots(states: list, active: int, phase: float = 1.0) -> list:
    """One dot per session, each in its own status colour, the followed one at full brightness.

    Position carries what a number could not: which of several sessions the rest of the panel is
    describing. Overflow past the dots that fit folds into the last one rather than being dropped,
    so the count never silently lies - and the fold keeps the loudest of the statuses it swallowed,
    since the point of a dot going red is that it is seen.

    Every busy session breathes, not just the followed one. Watching three windows work at once is
    the case this row exists for, and a single blinking dot answered a different question.
    """
    ops = []
    shown = min(len(states), MAX_DOTS)
    for i in range(shown):
        if i == shown - 1 and len(states) > MAX_DOTS:
            folded = states[i:]
            status = max(folded, key=lambda st: STATUS_RANK.get(st, 0))
            here = active >= i
        else:
            status = states[i]
            here = (i == active)

        if status == "idle" and not here:
            lit = IDLE_DOT
        else:
            base = STATUS_DOT.get(status, STATUS_DOT["idle"])
            level = 1.0 if here else OTHER_LEVEL
            if status == "busy":
                # The floor is absolute, not a fraction of this dot's own level. Multiplying the
                # two put an unfollowed busy dot at 0.066, which for a status colour any darker
                # than amber quantises to black - the exact disappearance the floor exists to
                # prevent.
                level = max(PULSE_FLOOR, level * phase)
            lit = _at_least_visible(tuple(min(255, round(c * level)) for c in base), base)
        # Three characters, as everywhere else in the layout. Four bits a channel was measured
        # against eight for this ramp and resolves all eleven steps of it, so there is nothing to
        # buy with the wider form.
        col = "".join(f"{c >> 4:X}" for c in lit)
        ops.append(["rect", DOTS_X + i * DOT_STEP, DOTS_Y, DOT_W, 1, col])
    return ops


def pulse(i: int, frames: int) -> float:
    """The clock's colon curve, floored so a dot never disappears entirely."""
    raised = 0.5 * (1.0 - math.cos(2 * math.pi * i / frames))
    return PULSE_FLOOR + (1.0 - PULSE_FLOOR) * raised


def gauge(y: int, pct: int, table, w: int = GAUGE_W, steps: int = 7, lo: float = 0.30) -> list:
    """One hue, brightness ramped along the fill so the lit end reads as the level."""
    base = _hue(pct, table)
    n = max(0, min(w, round(w * pct / 100)))
    ops = []
    for x in range(n):
        t = lo + (1.0 - lo) * (round(x / max(1, n - 1) * steps) / steps)
        ops.append(["px", x, y, "".join(f"{min(255, round(c * t)) >> 4:X}" for c in base)])
    if n < w:
        ops.append(["rect", n, y, w - n, 1, "111"])
    return ops


def bars_for(view: dict) -> list:
    """Both gauges, as empty tracks while there is no figure for them yet.

    A row that is simply absent and a row with nothing lit look the same at one pixel tall, so
    skipping the unknown one does not read as "no reading" - it reads as a layout with one gauge,
    and the bar that did draw reads as a stray line. That is every session's first minute, before
    any context figure has arrived.
    """
    return (gauge(6, view.get("quota") or 0, QUOTA_HUES)
            + gauge(7, view.get("context") or 0, CONTEXT_HUES))


NUMBER = "FFF"          # the value, bright
PREFIX_DIM = 0.55       # the letter, dimmed so the eye reads it as a label rather than a digit


def _dim(color, factor: float = PREFIX_DIM) -> str:
    """A dimmed three-character colour, from either an (r,g,b) tuple or a hex string."""
    if isinstance(color, (tuple, list)):
        rgb = list(color[:3])
    else:
        text = str(color).lstrip("#")
        if len(text) == 3:
            rgb = [int(c, 16) * 17 for c in text]
        elif len(text) == 6:
            rgb = [int(text[i:i + 2], 16) for i in (0, 2, 4)]
        else:
            rgb = [128, 128, 128]
    return "".join(f"{min(255, int(v * factor)) >> 4:X}" for v in rgb)


def labels_for(view: dict) -> list:
    """Every metric worth a glance, as (prefix, colour, value).

    The letter takes the colour of the gauge it belongs to and is dimmed; the number stays white.
    That does two jobs at once - it separates the label from the digits, which ran together when
    both were the same grey, and it ties `C` to the bar it describes.

    No percent sign. It cost four pixels to repeat what the letter already said, and at 3x5 it was
    the glyph most often mistaken for a digit.
    """
    out = []
    if view.get("context") is not None:
        out.append(("C", _dim(_hue(view["context"], CONTEXT_HUES)),
                    str(view["context"])))
    if view.get("quota") is not None:
        out.append(("U", _dim(_hue(view["quota"], QUOTA_HUES)),
                    str(view["quota"])))
    if view.get("agents"):
        out.append(("+", _dim("37F"), str(view["agents"])))
    if not out and view.get("tokens") is not None:
        out.append(("", NUMBER, f"{view['tokens'] // 1000}K"))
    return out


# A letter is 3 wide; the extra pixel of gap keeps it from reading as part of the number.
PREFIX_GAP = 5


def _draw(entry: tuple, x: int, y: int) -> list:
    prefix, colour, value = entry
    ops = []
    if prefix:
        ops.append(["text", x, y, prefix, colour])
        x += PREFIX_GAP
    ops.append(["text", x, y, value, NUMBER])
    return ops


def label_frames(view: dict, x: int, y: int = 0) -> list:
    """Dwell on each metric, then slide it up and out while the next rises into place.

    A slide rather than a swap because a value that changes without moving looks like a glitch on
    a panel this small - the movement is what says "this is a different number", not the digits.
    """
    if view.get("status") == "busy" and view.get("elapsed") is not None:
        # While it is working, how long it has been working is the one figure nothing else carries
        # and the only one that keeps changing on its own. No cycle needed.
        return [_draw(("T", _dim("FA2"), fmt_elapsed(view["elapsed"])), x, y)]

    labels = labels_for(view)
    if not labels:
        return [[]]
    if len(labels) == 1:
        return [_draw(labels[0], x, y)]

    frames = []
    for i, entry in enumerate(labels):
        nxt = labels[(i + 1) % len(labels)]
        frames += [_draw(entry, x, y)] * LABEL_DWELL
        # Six rows of travel takes the glyph clear of the band and brings the next one in behind it.
        for step in range(1, 7):
            frames.append(_draw(entry, x, y - step) + _draw(nxt, x, y - step + 6))
    return frames


def fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return str(s) if s < 60 else f"{s // 60}M"


_sent: dict = {}


def _layer(name: str, frames: list, z: int, fps: float, clip: list | None = None) -> None:
    """Only re-send a layer that actually changed.

    The elapsed clock ticks every second, and re-sending everything on each tick would restart the
    creature's walk from frame zero every second - the animation would never get past its first
    step.
    """
    sig = (z, fps, frames, tuple(clip) if clip else None)
    if _sent.get(name) == sig:
        return
    if pc.layer(name, frames, z=z, fps=fps, clip=clip) is not None:
        _sent[name] = sig


def reconcile() -> None:
    """Forget what we believe the server holds whenever it disagrees.

    _sent is this process's memory, not the daemon's state, and the two come apart in three ways: a
    daemon that restarted comes back with no layers, a console with control may drop one, and the
    daemon itself reaps a layer whose expiry has run out. In every case the missing layer is never
    redrawn, because as far as this renderer knows it was already sent - the panel keeps whatever
    survived, which looks like a rendering bug and is really a stale cache.

    Ownership removed one of those three causes and expiry added another, so this matters more than
    it did, not less.
    """
    got = pc.layers()
    if got is None:
        return
    # Ours only. Layers are namespaced by client now, so another tool's `bars` is not evidence that
    # ours survived - and comparing against everything on the panel would have us conclude it did.
    mine = {l.get("name") for l in (got.get("layers") or [])
            if l.get("owner") == pc.CLIENT}
    if mine != set(_sent):
        if _sent:
            log(f"server holds {sorted(mine)} of ours, resending everything")
        _sent.clear()


def paint(view: dict) -> None:
    if not view.get("live"):
        pc.clear()
        _sent.clear()
        return

    # The server ends itself after a few minutes without a client, which is how the clock gets its
    # panel back. So it has to be checked here, not once at startup: otherwise the first prompt
    # after a quiet spell draws into a socket nobody is listening on.
    if not ensure_server():
        return
    reconcile()

    look, walking = STATE_LOOK[view["status"]]
    if view["status"] == "idle":
        # Nothing to report is not nothing to look at: it dozes, wanders off and comes back.
        _layer("creature", claudlet.stroll(), 10, WALK_FPS)
    else:
        _layer("creature", claudlet.frames(look, walking), 10, WALK_FPS if walking else 0)

    # The band right of the creature and above the gauges. Sliding text travels a whole glyph
    # height, which without this would carry it across the two rows the gauges own.
    band = [claudlet.WIDTH + 2, 0, 32 - (claudlet.WIDTH + 2), 6]
    frames = label_frames(view, claudlet.WIDTH + 2, y=0)
    _layer("text", frames, 5, LABEL_FPS if len(frames) > 1 else 0, clip=band)

    _layer("bars", [bars_for(view)], 1, 0)

    # Its own layer, so the breath runs at its own rate without resending the gauges beside it.
    states, active = view.get("states") or [], view.get("active", 0)
    if "busy" in states:
        # Smooth rather than on/off: a hard blink on two pixels reads as a fault, a breath reads as
        # activity - which is the choice the firmware's own colon already makes.
        n = max(2, round(PULSE_MS / 1000.0 * LABEL_FPS))
        _layer("dots", [session_dots(states, active, pulse(i, n)) for i in range(n)], 2, LABEL_FPS)
    else:
        _layer("dots", [session_dots(states, active)], 2, 0)


# ---- single instance -----------------------------------------------------------------


def _mtime_of_self() -> float:
    """Newest mtime across the renderer and what it draws with, which is close enough to a version
    for deciding which of two processes is running older code."""
    here = os.path.dirname(os.path.realpath(__file__))
    best = 0.0
    for name in ("renderer.py", "claudlet.py"):
        try:
            best = max(best, os.path.getmtime(os.path.join(here, name)))
        except OSError:
            pass
    return best


def already_running() -> bool:
    """True when a live renderer should keep the job.

    A plain pidfile guard is not enough: one long session keeps a renderer alive for hours, and
    every later session then declines to start - so an edited plugin never takes effect, and
    neither does a `plugin update`. So the holder writes what version it is, and a newer arrival
    asks the old one to stand down instead of walking away.
    """
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            pid_s, _, stamp_s = f.read().strip().partition(" ")
            pid = int(pid_s)
            stamp = float(stamp_s or 0)
    except Exception:
        return False
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False                        # stale pidfile
    if _mtime_of_self() > stamp + 1.0:
        log(f"replacing renderer {pid}, which is running older code")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(40):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                return False                # it stood down
        log(f"renderer {pid} did not stand down")
    return True


def claim() -> None:
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    tmp = f"{PIDFILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {_mtime_of_self():.0f}")
    os.replace(tmp, PIDFILE)


def release() -> None:
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            if int(f.read().strip().split()[0]) == os.getpid():
                os.unlink(PIDFILE)
    except Exception:
        pass


def main(argv: list[str]) -> int:
    once = "--once" in argv
    if not once and already_running():
        log("another renderer holds the pidfile, exiting")
        return 0
    if once:
        paint(collect(time.time()))
        return 0

    claim()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log(f"start pid={os.getpid()} poll={POLL}s ttl={TTL:.0f}s "
        f"window={WINDOW or 'auto'}")
    last = None
    try:
        while not STOP:
            view = collect(time.time())
            if view != last:
                log(f"paint {view}")
                paint(view)
                last = view
            if not view.get("live"):
                log("no live sessions, panel handed back")
                return 0
            time.sleep(POLL)
        log("asked to stop")
        return 0
    except Exception as exc:
        log(f"error {exc!r}")
        return 1
    finally:
        if last and last.get("live"):
            log("clearing on the way out")
            pc.clear()
        release()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
