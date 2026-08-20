---
description: Fill in the panel's quota gauge by chaining a filter in front of whatever owns statusLine
---

Wire the optional statusline filter so the panel's second gauge shows the 5-hour quota, and the
context gauge uses Claude Code's own figure instead of an estimate.

**Everything else about the plugin works without this.** Only proceed if the user asked for it.

## Why it has to be a chain

`context_window.used_percentage`, `rate_limits.five_hour` and `cost.total_cost_usd` are handed
only to the **statusline** command, and Claude Code allows exactly one of those. Something usually
already owns it — `claude-hud`, for instance. So the filter goes *in front*: it keeps a copy of the
JSON for the panel and then execs whatever owned the slot before, unchanged.

## Steps

1. **Read the current setting.** Look in the user's settings file — `$CLAUDE_CONFIG_DIR/settings.json`
   if that is set, otherwise `~/.claude/settings.json` — for `statusLine.command`.

   Report what you find and stop for confirmation before writing anything. Three cases:

   - **Already our wrapper** (`statusline-wrapper.sh`): nothing to do. Say so and stop.
   - **Some other command**: that string becomes `AWTRIX_PANEL_STATUSLINE`, so it keeps running.
   - **Missing, or pointing at a file that does not exist**: say so. There is nothing to chain,
     and the wrapper alone prints an empty statusline. Ask whether they want it anyway.

2. **Check the file it points at actually exists.** A `statusLine.command` naming a missing file
   is common and means the statusline is already broken; chaining onto it will not fix that, and
   silently making it our problem is worse than saying it.

3. **Write the settings**, preserving every other key. `env` is how the wrapper learns what to
   call — hooks and the statusline both inherit it:

   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "${CLAUDE_PLUGIN_ROOT}/hooks/statusline-wrapper.sh",
       "refreshInterval": 5
     },
     "env": {
       "AWTRIX_PANEL_FILTER": "${CLAUDE_PLUGIN_ROOT}/hooks/from-statusline.py",
       "AWTRIX_PANEL_STATUSLINE": "<whatever command was there before>"
     }
   }
   ```

   Expand `${CLAUDE_PLUGIN_ROOT}` to the real absolute path — `settings.json` is not a place that
   substitution happens. Keep any `refreshInterval` the user already had; 5 seconds is a good
   default and is what keeps the gauges moving between messages.

4. **Verify.** After the next message lands, the statusline should look exactly as it did before,
   and the session's file under `~/.local/state/awtrix-panel/sessions/` should have gained
   `quota_5h` and `context_pct`. Show the user those two keys as proof rather than asserting it
   worked.

## Backing it out

Restore `statusLine.command` to the value now in `AWTRIX_PANEL_STATUSLINE` and drop the two `env`
keys. The panel keeps working; the quota gauge just goes empty again.
