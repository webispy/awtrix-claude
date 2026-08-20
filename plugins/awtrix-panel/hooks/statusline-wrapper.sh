#!/bin/sh
# Front half of a statusline chain: tee the payload to the panel, then hand it on untouched.
#
# Claude Code allows one statusLine command, and something usually already owns it. This takes
# that slot, keeps a copy of the JSON for the panel, and execs whatever owned it before - so the
# HUD is unchanged and our half cannot take it down.
#
# AWTRIX_PANEL_STATUSLINE is the command that used to be in settings.json. With it unset this
# prints nothing, which is a valid statusline.

json=$(cat)

if [ -n "$AWTRIX_PANEL_FILTER" ] && [ -x "$AWTRIX_PANEL_FILTER" ]; then
    printf '%s' "$json" | "$AWTRIX_PANEL_FILTER" >/dev/null 2>&1 || :
elif [ -n "$AWTRIX_PANEL_FILTER" ]; then
    printf '%s' "$json" | python3 "$AWTRIX_PANEL_FILTER" >/dev/null 2>&1 || :
fi

if [ -n "$AWTRIX_PANEL_STATUSLINE" ]; then
    printf '%s' "$json" | exec sh -c "$AWTRIX_PANEL_STATUSLINE"
fi
