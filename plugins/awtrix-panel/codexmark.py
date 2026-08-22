"""A 13x6 Codex terminal mark for the panel's agent band.

Codex identifies itself as ``>_`` in its own terminal header. At this resolution that mark remains
recognisable where a reduced OpenAI knot would become an arbitrary cluster of pixels.
"""

from __future__ import annotations

WIDTH, HEIGHT = 13, 6

CHEVRON = (
    (1, 0), (2, 0),
    (3, 1), (4, 1),
    (5, 2), (6, 2),
    (3, 3), (4, 3),
    (1, 4), (2, 4),
)
CURSOR = tuple((x, 5) for x in range(7, 12))
SPARK = ((10, 1), (11, 1), (10, 2), (11, 2))

COLOURS = {
    "busy": ("4DF", "FFF"),
    "permission": ("FA2", "FFF"),
    "error": ("F54", "FBA"),
    "idle": ("278", "7AB"),
}


def _frame(status: str, cursor: str | None, spark: bool = False) -> list:
    body, default_cursor = COLOURS.get(status, COLOURS["idle"])
    ops = [["px", x, y, body] for x, y in CHEVRON]
    if cursor:
        ops += [["px", x, y, cursor or default_cursor] for x, y in CURSOR]
    if spark:
        ops += [["px", x, y, "FFF"] for x, y in SPARK]
    return ops


def frames(status: str) -> tuple[list, float]:
    """Frames and their rate; activity moves only the cursor, keeping serial deltas small."""
    _, cursor = COLOURS.get(status, COLOURS["idle"])
    if status == "busy":
        return ([_frame(status, colour) for colour in ("255", "399", "5CC", cursor, "5CC", "399")], 6.0)
    if status == "permission":
        return ([_frame(status, cursor, spark=True), _frame(status, cursor)], 2.0)
    if status == "error":
        return ([_frame(status, cursor), _frame(status, None)], 2.0)
    return ([_frame(status, cursor), _frame(status, "345")], 0.5)
