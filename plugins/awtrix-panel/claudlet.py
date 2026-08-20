"""The creature, adapted for a 32x8 panel.

Artwork derived from claudlet (https://github.com/YeeDochi/Claudlet), whose creature is dedicated
to the public domain under CC0 1.0. The original renders at 19x11 art pixels with a four-colour
palette; this keeps the palette and the structure that carries its identity - the horizontal loaf,
two eyes, the row that juts out on both sides, four stubby legs, the top highlight - and squeezes
it to 13x6 so the bottom two rows are free for gauges.

Do not "improve" the silhouette. An earlier attempt gave it arms and two legs instead of four, and
it stopped reading as the same creature at all.
"""

from __future__ import annotations

# CC0 palette, in the firmware's three-character colour form to keep payloads small.
HI, BODY, SHADE, EYE, PALE = "EA8", "D75", "B53", "322", "FDC"

WIDTH, HEIGHT = 13, 6

# Rows 0..4 are the body; row 5 is the legs, which is the only row a walk cycle touches.
_BODY = """
..*********..
..%%%%%%%%%..
@@%%#%%%#%%@@
@@%%%%%%%%%@@
..@@@@@@@@@..
"""

# One entry per gait phase. Lifting a leg means dropping its pixel, exactly as the original does.
_LEGS = (
    "..@·@·@·@·@··",
    "..@···@·@···@",
    "..@·@·@·@·@··",
    "..·@·@···@·@·",
)

_PAL = {"*": HI, "%": BODY, "@": SHADE, "#": EYE, "+": PALE, "W": "FFF"}


def _ops(grid: str, oy: int = 0, ox: int = 0) -> list:
    out = []
    for y, line in enumerate(grid.strip("\n").split("\n")):
        for x, ch in enumerate(line):
            if ch in _PAL:
                out.append(["px", x + ox, y + oy, _PAL[ch]])
    return out


def _body_for(state: str) -> str:
    """Expressions follow the original's: the eyes move or close, and error goes pale."""
    if state == "ask":
        # Eyes a row higher and a mark above, the way the original's `asking` reads.
        return """
..****W****..
..%%#%%%#%%..
@@%%#%%%#%%@@
@@%%%%%%%%%@@
..@@@@@@@@@..
"""
    if state == "think":
        return """
..****W****..
..%%#%%%#%%..
@@%%%%%%%%%@@
@@%%%%%%%%%@@
..@@@@@@@@@..
"""
    if state == "sleep":
        return """
..*********..
..%%%%%%%%%..
@@%###%###%@@
@@%%%%%%%%%@@
..@@@@@@@@@..
"""
    if state == "error":
        return """
..+++++++++..
..++#+++#++..
@@%%#%%%#%%@@
@@%%%%%%%%%@@
..@@@@@@@@@..
"""
    return _BODY


def frames(state: str, walking: bool) -> list:
    """One frame when still, the whole gait when walking. The body is identical across a walk, so
    only the leg row differs and the delta the server sends stays tiny."""
    body = _ops(_body_for(state))
    if not walking:
        return [body + _ops(_LEGS[0], oy=5)]
    return [body + _ops(legs, oy=5) for legs in _LEGS]


def _shift(ops: list, dx: int) -> list:
    return [[op[0], op[1] + dx, op[2], op[3]] for op in ops]


def stroll(dwell: int = 10, step: int = 2, away: int = 5) -> list:
    """The idle loop: doze, wander off to the left, come back, doze again.

    A creature that never moves reads as a static image, and the panel has the frames to spare -
    a leg row is the only thing that changes while it walks, so the server's deltas stay small
    whatever the sprite is doing. Steps of two pixels rather than one keep the cycle short enough
    that the whole thing fits in one layer without the socket carrying tens of kilobytes.
    """
    asleep = _ops(_body_for("sleep")) + _ops(_LEGS[0], oy=5)
    awake = _ops(_body_for("idle"))
    out = [asleep] * dwell

    gait = 0
    for dx in range(0, -(WIDTH + 1), -step):        # walk off the left edge
        out.append(_shift(awake + _ops(_LEGS[gait % len(_LEGS)], oy=5), dx))
        gait += 1
    out += [[]] * away                              # gone
    for dx in range(-(WIDTH + 1) + step, 1, step):  # and back in
        out.append(_shift(awake + _ops(_LEGS[gait % len(_LEGS)], oy=5), dx))
        gait += 1
    return out
