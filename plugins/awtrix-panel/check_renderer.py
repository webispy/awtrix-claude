#!/usr/bin/env python3
"""Fail if the panel's layout logic draws the wrong thing.

`renderer.py` decides what the 32x8 panel says: which dot belongs to which session, how a gauge
ramps, what the cycling label reads. None of it touches hardware, and all of it has been checked by
eye - which is how a label lost its currency symbol to a font with no glyph for it, and how three
dot-ordering mistakes survived at once. Four pixels are not enough to eyeball.

Run: python plugins/awtrix-panel/check_renderer.py     (exit 1 on failure)
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Away from the checkout, and with the wake suppressed: importing the renderer to ask it what colour
# a dot is must not put anything on the real panel. A separate home is not enough on its own - it
# gets its own socket, but there is only one serial port and a spawned server would take it.
os.environ.setdefault("AWTRIX_PANEL_HOME", os.path.join(tempfile.gettempdir(), "awtrix-check"))
os.environ.setdefault("AWTRIX_PANEL_NO_SPAWN", "1")

import renderer as r  # noqa: E402

FAILED = []


def check(name, got, want):
    if got != want:
        FAILED.append(f"{name}: got {got!r}, want {want!r}")


def cols(ops):
    """The colour of each dot, left to right, as the six-character form the layer carries."""
    return [op[5] for op in sorted(ops, key=lambda o: o[1])]


def xs(ops):
    return [op[1] for op in sorted(ops, key=lambda o: o[1])]


def col3(rgb, level=1.0):
    return "".join(f"{min(255, round(c * level)) >> 4:X}" for c in rgb)


GREY, BUSY = col3(r.IDLE_DOT), col3(r.STATUS_DOT["busy"])
PERM, WHITE = col3(r.STATUS_DOT["permission"]), col3(r.STATUS_DOT["idle"])

# ---- geometry ------------------------------------------------------------------------

check("four dots fit", r.MAX_DOTS, 4)
check("dots sit on the bottom row", {op[2] for op in r.session_dots(["idle"] * 3, 0)}, {7})
check("dots are two wide", {op[3] for op in r.session_dots(["idle"] * 3, 0)}, {2})
check("dots are one row tall", {op[4] for op in r.session_dots(["idle"] * 3, 0)}, {1})
check("dots step by three", xs(r.session_dots(["idle"] * 4, 0)), [21, 24, 27, 30])
check("dots stay inside the panel", max(xs(r.session_dots(["idle"] * 4, 0))) + 2, 32)
check("no sessions, no dots", r.session_dots([], 0), [])

# ---- who is which --------------------------------------------------------------------

# The followed session is the bright one; an idle session that is not followed stays grey.
check("active idle is white", cols(r.session_dots(["idle", "idle"], 0)), [WHITE, GREY])
check("active follows the index", cols(r.session_dots(["idle", "idle"], 1)), [GREY, WHITE])

# A session's own status colours its own dot, followed or not - dimmer when it is not.
check("another session's trouble still shows",
      cols(r.session_dots(["idle", "permission"], 0))[1],
      col3(r.STATUS_DOT["permission"], r.OTHER_LEVEL))
check("the followed session is the bright one",
      cols(r.session_dots(["permission", "permission"], 0)), [PERM, cols(r.session_dots(["permission", "permission"], 0))[1]])
check("followed permission is full strength", cols(r.session_dots(["permission", "idle"], 0))[0], PERM)

# ---- overflow ------------------------------------------------------------------------

# More sessions than dots folds into the last one rather than dropping any.
check("overflow draws no more than fits", len(r.session_dots(["idle"] * 9, 0)), 4)
# The followed session here is dot 0, so the fold shows its trouble at the quieter level.
check("the fold keeps the loudest status it swallowed",
      cols(r.session_dots(["idle", "idle", "idle", "idle", "permission", "idle"], 0))[3],
      col3(r.STATUS_DOT["permission"], r.OTHER_LEVEL))
check("the fold is bright when the followed session is inside it",
      cols(r.session_dots(["idle", "idle", "idle", "idle", "permission"], 4))[3], PERM)
# An active session beyond the fold is represented by the folded dot, not lost.
check("active beyond the fold lights the fold",
      cols(r.session_dots(["idle"] * 6, 5))[3], WHITE)

# ---- the breath ----------------------------------------------------------------------

check("pulse starts at the floor", round(r.pulse(0, 20), 4), round(r.PULSE_FLOOR, 4))
check("pulse peaks at one", round(r.pulse(10, 20), 4), 1.0)
check("pulse returns", round(r.pulse(20, 20), 4), round(r.PULSE_FLOOR, 4))
check("pulse never leaves the range",
      [t for t in (round(r.pulse(i, 20), 6) for i in range(20)) if not r.PULSE_FLOOR - 1e-9 <= t <= 1.0], [])
# Symmetric, which is what makes it read as breathing rather than as a sawtooth.
check("pulse rises and falls alike", round(r.pulse(4, 20), 6), round(r.pulse(16, 20), 6))

# One full period at the layer's own rate, matching the firmware's colon.
check("a breath lasts two seconds", max(2, round(r.PULSE_MS / 1000.0 * r.LABEL_FPS)) / r.LABEL_FPS,
      r.PULSE_MS / 1000.0)

# Only busy dots breathe; the others hold still through the whole cycle.
dim, bright = r.session_dots(["busy", "permission"], 0, r.PULSE_FLOOR), r.session_dots(["busy", "permission"], 0, 1.0)
check("a busy dot dims with the phase", cols(dim)[0] != cols(bright)[0], True)
check("a dot that is not busy holds still", cols(dim)[1], cols(bright)[1])
check("full phase is the plain colour", cols(bright)[0], BUSY)

# Every busy session breathes, not only the followed one.
check("an unfollowed busy dot breathes too",
      cols(r.session_dots(["idle", "busy"], 0, r.PULSE_FLOOR))[1]
      != cols(r.session_dots(["idle", "busy"], 0, 1.0))[1], True)

# The curve is symmetric, so a 20-frame cycle visits 11 distinct points, and at four bits a channel
# every one of them still has to survive as its own colour - otherwise the breath holds still for
# two frames somewhere and the eye catches it.
check("colours are three characters", {len(c) for c in cols(r.session_dots(["busy", "idle"], 0))}, {3})
rising = [cols(r.session_dots(["busy"], 0, r.pulse(i, 20)))[0] for i in range(11)]
check("every step of the ramp survives the encoding", len(set(rising)), len(rising))
check("the ramp only rises", [int(v[0], 16) for v in rising], sorted(int(v[0], 16) for v in rising))

# Nothing may go out entirely at the bottom of a breath. Only busy dots breathe, so the colour
# under test has to be the busy one - including a colour darker than the amber it happens to be
# today, since the floor was multiplied by the dot's own level and that is what hid the bug.
_amber = r.STATUS_DOT["busy"]
for label, base in (("amber", _amber), ("a darker colour", (0x80, 0x40, 0x20)),
                    ("a very dark colour", (0x30, 0x18, 0x08))):
    r.STATUS_DOT["busy"] = base
    for who, at in (("followed", 0), ("unfollowed", 1)):
        if cols(r.session_dots(["busy", "busy"], at, r.PULSE_FLOOR))[1 - at] == "000":
            FAILED.append(f"an {who}-alongside {label} busy dot goes out at the bottom of a breath")
    # The floor applies to the dot's own level rather than being a share of it. For a colour
    # bright enough to survive the four-bit grid that is exactly PULSE_FLOOR of the base.
    if col3(base, r.PULSE_FLOOR) != "000":
        check(f"the floor is absolute for {label}",
              cols(r.session_dots(["busy", "busy"], 0, r.PULSE_FLOOR))[1], col3(base, r.PULSE_FLOOR))
r.STATUS_DOT["busy"] = _amber

# ---- the gauges ----------------------------------------------------------------------

# Two rows, always. A gauge with nothing to report is an empty track rather than an absent one: at
# one pixel tall the two look alike, so a session's first minute - which has no context figure yet -
# drew a single bar that read as a stray line instead of as one of a pair.
check("both rows are drawn before any figure arrives", {op[2] for op in r.bars_for({})}, {6, 7})
check("an unknown gauge is a full-width track", r.bars_for({}),
      [["rect", 0, 6, r.GAUGE_W, 1, "333"], ["rect", 0, 7, r.GAUGE_W, 1, "333"]])
check("unknown and zero look the same", r.bars_for({"quota": 0, "context": 0}), r.bars_for({}))
check("a gauge with a figure lights up",
      len([op for op in r.bars_for({"context": 50}) if op[0] == "px"]), r.GAUGE_W // 2)
check("the gauges stop at the same column",
      {op[1] + op[3] for op in r.bars_for({}) if op[0] == "rect"}, {r.GAUGE_W})

# Prefixes and values are separate text operations so they can carry different colours. Their
# second x coordinate must follow the variable-width panel font rather than the old fixed cell.
check("a normal prefix leaves its extra column", r._draw(("C", "555", "50"), 8, 0)[1][1], 13)
check("a wide M prefix leaves its extra column", r._draw(("M", "555", "G56"), 8, 0)[1][1], 15)
check("four-pixel N and O prefixes leave their extra column",
      [r._draw((prefix, "555", "1"), 8, 0)[1][1] for prefix in ("N", "O")], [14, 14])

# ---- agent-specific input and display -------------------------------------------------

# Claude JSONL remains one input. Codex telemetry is supplied by its numeric rollout reader rather
# than interpreted as a Claude transcript.
with tempfile.TemporaryDirectory() as state_dir:
    transcript = os.path.join(state_dir, "transcript.jsonl")
    with open(transcript, "w", encoding="utf-8") as f:
        f.write(json.dumps({"message": {"usage": {"input_tokens": 50000}}}) + "\n")
    r.SESSIONS = state_dir
    now = time.time()
    session_file = os.path.join(state_dir, "codex.json")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump({"session_id": "codex", "event": "Stop", "status": "idle",
                   "agent": "codex", "transcript": transcript, "updated": now}, f)
    codex_view = r.collect(now)
    check("Codex sessions keep their identity", codex_view.get("agent"), "codex")
    check("Codex transcripts are not parsed as Claude", codex_view.get("tokens"), None)

# The Codex mark owns exactly the same band as the creature and never draws outside it.
for status in r.STATE_LOOK:
    frames, fps = r.codexmark.frames(status)
    check(f"Codex {status} has frames", bool(frames), True)
    points = [(op[1], op[2]) for frame in frames for op in frame]
    check(f"Codex {status} stays in width", all(0 <= x < r.codexmark.WIDTH for x, _ in points), True)
    check(f"Codex {status} stays in height", all(0 <= y < r.codexmark.HEIGHT for _, y in points), True)
check("busy Codex mark animates", r.codexmark.frames("busy")[1] > 0, True)
check("Codex mark and creature share width", r.codexmark.WIDTH, r.claudlet.WIDTH)

view = {
    "status": "idle", "context": 50, "quota": 31, "elapsed": None, "tokens": 2_500_000,
    "metrics": {"context": 50, "quota_primary": 31, "quota_secondary": 12,
                "tokens_total": 2_500_000, "model": "gpt-5.6-sol"},
}
custom = {"gauges": ["quota_secondary", "context"],
          "labels": ["model", "tokens_total"], "busy_label": None, "symbol": "codex"}
check("configured gauges select their metrics",
      len([op for op in r.bars_for(view, custom) if op[0] == "px"]), round(r.GAUGE_W * .12) + 10)
check("configured labels keep their order", [entry[0] for entry in r.labels_for(view, custom)], ["M", "N"])

with tempfile.TemporaryDirectory() as state_dir:
    r.SESSIONS = state_dir
    now = time.time()
    with open(os.path.join(state_dir, "live-codex.json"), "w", encoding="utf-8") as f:
        json.dump({"session_id": "live-codex", "event": "UserPromptSubmit", "status": "busy",
                   "agent": "codex", "updated": now - r.TTL - 10}, f)
    old_read = r.codexusage.read
    r.codexusage.read = lambda *_: {
        "updated": now, "context_tokens": 100000, "context_window": 200000,
        "context_pct": 50, "model": "gpt-5.6-sol", "cli_version": "0.149.0",
        "usage_last": {"total_tokens": 100100},
        "usage_total": {"input_tokens": 2000000, "cached_input_tokens": 1500000,
                        "output_tokens": 4000, "reasoning_output_tokens": 1000,
                        "total_tokens": 2005000},
        "rate_limits": {"primary": {"used_percent": 31, "resets_at": now + 3600},
                        "secondary": {"used_percent": 12, "resets_at": now + 7200},
                        "credits": {"balance": "7"}, "plan_type": "plus"},
    }
    live = r.collect(now)
    r.codexusage.read = old_read
    check("rollout activity keeps a long Codex turn live", live.get("live"), 1)
    check("Codex context reaches the common view", live.get("context"), 50)
    check("Codex primary quota reaches the common view", live.get("quota"), 31)
    check("Codex secondary quota is retained", live.get("quota_secondary"), 12)
    check("all token lanes are retained", live["metrics"]["tokens_reasoning"], 1000)
    check("Codex identity is retained", live["metrics"]["model"], "gpt-5.6-sol")

with tempfile.TemporaryDirectory() as config_dir:
    path = os.path.join(config_dir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"display": {"gauges": ["context", "quota_primary"]},
                   "agents": {"codex": {"symbol": "codex", "labels": ["model"]}}}, f)
    config = r.panelconfig.load(path)
    codex_display = r.panelconfig.for_agent(config, "codex")
    check("agent config inherits global gauges", codex_display["gauges"],
          ["context", "quota_primary"])
    check("agent config overrides its symbol", codex_display["symbol"], "codex")
    check("agent config overrides label order", codex_display["labels"], ["model"])

# ---- reconciling with the daemon ------------------------------------------------------

# The dedupe cache has to yield to what the daemon actually holds, or a layer that went missing
# stays gone: this renderer would never send it again. Three things can take one away now - a
# restarted daemon, a console with control, and the daemon reaping a layer whose expiry ran out.


def held(*names, owner=None):
    """A `layers` reply listing these as belonging to us, or to somebody else."""
    who = r.pc.CLIENT if owner is None else owner
    return lambda: {"ok": True, "layers": [{"name": n, "owner": who} for n in names]}


r._sent.clear()
r._sent.update({"creature": 1, "text": 2, "dots": 3})
r.pc.layers = held("creature", "text", "dots")
r.reconcile()
check("agreement keeps the cache", sorted(r._sent), ["creature", "dots", "text"])

r.pc.layers = held("dots")
r.reconcile()
check("a layer that went missing empties the cache", sorted(r._sent), [])

r._sent.update({"creature": 1})
r.pc.layers = held()
r.reconcile()
check("a restarted daemon empties the cache", sorted(r._sent), [])

# Layers are namespaced by client, so somebody else's `creature` is not evidence that ours
# survived. Comparing against everything on the panel would have concluded that it did.
r._sent.update({"creature": 1})
r.pc.layers = held("creature", owner="pixelwire-web")
r.reconcile()
check("another client's layer of the same name is not ours", sorted(r._sent), [])

r._sent.update({"creature": 1})
r.pc.layers = lambda: None
r.reconcile()
check("no daemon leaves the cache alone", sorted(r._sent), ["creature"])

if FAILED:
    print(f"check_renderer: {len(FAILED)} failure(s)")
    for line in FAILED:
        print(f"  {line}")
    sys.exit(1)
print("renderer: dot geometry, per-session status, overflow, the gauges and the breath all check out.")
