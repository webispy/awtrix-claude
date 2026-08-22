# awtrix-panel

Whether Claude Code or Codex is working, waiting or asking you something — on a 32×8 LED panel,
next to the clock it normally shows. Claude keeps its walking crab; Codex uses the `>_` mark from
its terminal header, with the cursor moving while it works.

```
  ┌─────────────────────────────────┐
  │  *********                      │   a creature that walks while an agent works,
  │  %%%%%%%%%     T 4 2            │   stops and looks up when it needs you,
  │@@%%#%%%#%%@@                    │   and closes its eyes when there is nothing to do
  │@@%%%%%%%%%@@                    │
  │  @@@@@@@@@                      │   a letter for what the number is: T elapsed,
  │  @·@·@·@·@                      │   C context, U 5-hour quota, + subagents
  │▓▓▓▓▓░░░░░░░░░░░░░░░  ▪▪ ▪▪ ▪▪  │   5-hour quota, then one mark per live session
  │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░           │   context, one hue with the lit end at the level
  └─────────────────────────────────┘
```

While it is showing, the panel is this rather than a clock - that is the trade for smooth
animation. It hands the display back as soon as every session goes quiet, and `pixelwire stop` does it
at once.

## Requirements

| | |
|---|---|
| Hardware | Ulanzi TC001, or any AWTRIX NG board, **on a USB cable** |
| Firmware | [`webispy/awtrix-ng`](https://github.com/webispy/awtrix-ng) branch `serial-control` — the serial channel is not in upstream AWTRIX NG |
| Display server | [`pixelwire`](https://github.com/webispy/pixelwire) — `pixelwired` on `PATH`. It owns the port and composites; this plugin only decides what to draw |
| Runtime | `python3` for the hooks and the renderer, standard library only |

The panel does **not** need to be on your network — that is the whole point of driving it over the
cable. Setup for the firmware is in the
[repository README](https://github.com/webispy/awtrix-agents), and for the display server in
[pixelwire's](https://github.com/webispy/pixelwire).

## Install

Claude Code:

```
/plugin marketplace add webispy/awtrix-agents
/plugin install awtrix-panel@awtrix-agents
```

Codex CLI:

```bash
codex plugin marketplace add webispy/awtrix-agents
codex plugin add awtrix-panel@awtrix-agents
```

That is all. The hooks ship with the plugin, so nothing has to be added to `settings.json`, and the
renderer starts itself on the next session.

Check it is wired up:

```bash
pixelwire stat                                 # the display server is up and holding the panel
tail -f ~/.local/state/awtrix-panel/renderer.log
```

Only sessions started *after* the install have the hooks: both agents read hook configuration when
a session starts, so windows that were already open report nothing until they are restarted. An
empty `~/.local/state/awtrix-panel/sessions/` while a session is plainly busy means exactly that.

### Working on the plugin itself

`plugin install` copies the plugin into `<config>/plugins/cache/<marketplace>/<plugin>/<version>/`
and `${CLAUDE_PLUGIN_ROOT}` points at that copy, not at your checkout - true even when the
marketplace is a local directory. `plugin update` compares only the version string, so editing a
file changes nothing that runs, and the copy silently stays at whatever the code looked like when it
was installed.

Two ways out. Bump `version` in `.claude-plugin/plugin.json` and re-run `plugin update`, which is
what a release does anyway. Or, to iterate without a version bump each time, replace the cached
directory with a link to the checkout:

```bash
CACHE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache/awtrix-agents/awtrix-panel/0.3.0"
rm -rf "$CACHE" && ln -s "$PWD/plugins/awtrix-panel" "$CACHE"
```

Then the long-lived processes handle the rest: a waking hook retires a renderer older than the files
on disk, and the renderer does the same for a display server *it* started, so an edit reaches every
open session on its next prompt. A `pixelwired` you started yourself is left alone - it says so in
the log and carries on drawing. Reinstalling the plugin restores the copy.

## How it works

```
  hooks ──→ sessions/<id>.json ──→ renderer ──→ pixelwired ──→ panel
  (1 ms, no serial)   contract    (what to show)  (how it gets there)
```

Three processes, each with one job, because two constraints force the shape.

**A serial port has exactly one owner, and hooks fire concurrently** — so the hooks never touch it.
Each merges a few fields into a per-session file and exits: standard library only, no network, no
serial, every failure swallowed, because a hook that blocks costs you your session.

**Animation cannot pay to open the port per frame** — so `pixelwired`, the
[display server](https://github.com/webispy/pixelwire), holds it
open, composites named layers into a 32×8 framebuffer, and streams only the pixels that changed. A
walk cycle moves about six of them: thirty bytes a frame, against the eight hundred the same sprite
costs as draw commands.

The renderer sits between them and decides *what* to show. It **ends itself** once every session
file has gone stale, which is also when the panel is handed back and the clock returns.

Each link brings the next one back rather than assuming it is there: any hook that means activity
starts the renderer if its pid is gone, the renderer starts the display server before every paint if
nothing answers, a newer renderer asks an older one to stand down so an edited plugin takes effect,
and a second display server steps aside rather than stealing a live socket. Three processes with four ways to die needed four
ways to recover, and each of those was found by the panel going quiet.

Several sessions share one panel: the most demanding status wins (asking beats working beats idle),
subagents are summed, and the label carries the count.

### Agent symbols

The left band follows the active session's agent. Claude uses the claudlet-derived crab; Codex uses
a 13×6 `>_` terminal mark. Both animate only a small changing part — legs or cursor — so the serial
delta remains small.

| Status | Looks like |
|---|---|
| working | eyes open, **walking** |
| waiting for you to approve | stops, eyes up with a mark above |
| the turn ended badly | goes pale |
| idle | eyes closed |

For Codex, working animates the cursor, permission adds a flashing mark, error blinks the cursor,
and idle leaves a slow terminal-cursor pulse. `display.symbol` can force either symbol or hide it.

The label beside it says whatever the picture cannot. While a turn is running it is `T` and how long
it has been running, which is the one figure nothing else carries and the only one that keeps moving
on its own - no cycling, because a number that changes is already telling you it is alive. Otherwise
it cycles through what there is: `C` context, `U` the 5-hour quota, `+` a subagent count when one is
running. The letter takes the colour of the gauge it belongs to and is dimmed; the number stays
white. With nothing else to show it falls back to the raw token count.

Artwork adapted from [claudlet](https://github.com/YeeDochi/Claudlet), whose creature its authors
dedicated to the public domain under CC0 1.0. The original is 19×11 art pixels; this keeps the
palette and the structure that carries its identity — the horizontal loaf, two eyes, the row that
juts out on both sides, four stubby legs — squeezed into the six rows a 32×8 panel can spare, with
the bottom two left for the gauges.

### What it reads

| Shown | From |
|---|---|
| status | `SessionStart`, `UserPromptSubmit`, `PermissionRequest`, `Stop`; Claude also reports `StopFailure` |
| a session going away | `SessionEnd` — the file is deleted, so its mark leaves the row within the second rather than after the TTL |
| subagent count | `SubagentStart` / `SubagentStop` |
| current/recent tool and compaction count | tool and compact lifecycle hooks; Codex also falls back to the rollout tool name |
| Claude context | the newest transcript turn; its optional statusline supplies exact context, 5-hour and 7-day quota, and cost |
| Codex context and usage | numeric `token_count` events in the local rollout: current context, recent and cumulative token detail |
| Codex account limits | primary and secondary usage, window and reset, credits, plan and limit state from the same event |
| Codex session metadata | model, reasoning effort, CLI version, provider and origin from session/turn metadata |

Tool events are collected even when the default display does not select them; `tool` can be added
to the configured label cycle. Codex discovers `hooks/hooks.json`; Claude uses `hooks/claude.json`
through its manifest so each agent receives only events and output conventions it supports. Codex
CLI 0.149.0 does not emit tool hooks for its shell executor, so the reader also extracts the bounded
tool name from the rollout envelope without decoding its input or output.

The Codex rollout format is an implementation detail, not a documented plugin API. The reader is
therefore defensive: every field is optional, truncation and replacement reset its incremental
cursor, and an unknown shape becomes an unknown metric rather than a broken hook. It checks only
`session_meta`, `turn_context`, `token_count`, and the name in tool envelopes. Prompt, response,
reasoning, and tool content are skipped before JSON decoding and are never copied to the panel
state or renderer log.

### Context is measured, not guessed

Claude Code does not tell a hook how large the context window is. Rather than make you configure it,
the divisor starts at the usual 200,000 and steps up to the next tier the moment a turn is seen that
could not have fitted in it — a model with a bigger window says so by holding more tokens than a
smaller one could. Nothing to set, and the gauge on a 1M-context model no longer reads five times too
full. `AWTRIX_PANEL_CONTEXT_WINDOW` overrides it if you want a fixed divisor.

The authoritative figure, and the 5-hour and 7-day quota with it, only reaches a statusline command.
Wiring that up is optional and described below; the plugin works without it.

## Configuration

Display selection lives separately from collection. Copy `config.example.json` to
`~/.config/awtrix-panel/config.json`, or point `AWTRIX_PANEL_CONFIG` at another file. Changes are
read while the renderer runs; no reinstall is needed.

```json
{
  "display": {
    "symbol": "auto",
    "gauges": ["quota_primary", "context"],
    "labels": ["context", "quota_primary", "quota_secondary", "subagents", "tokens_total"],
    "busy_label": "elapsed"
  },
  "agents": {
    "codex": {
      "symbol": "codex",
      "labels": ["context", "quota_primary", "quota_primary_reset", "model"]
    }
  }
}
```

`agents.claude` and `agents.codex` override the global `display` one key at a time. `symbol` accepts
`auto`, `claude`, `codex` or `none`. `gauges` chooses the top and bottom percentage rows; an unknown
value remains an empty track. `labels` is the idle-cycle order, and `busy_label` is the one metric
held while work is running — set it to `null` to cycle labels while busy too.

Available metrics:

| Group | Names |
|---|---|
| lifecycle | `elapsed`, `sessions`, `subagents`, `tool`, `compactions` |
| context | `context`, `context_remaining`, `tokens_context` |
| quota | `quota_primary`, `quota_secondary`, `quota_primary_reset`, `quota_secondary_reset`, `credits` |
| tokens | `tokens_last`, `tokens_input`, `tokens_cached`, `tokens_output`, `tokens_reasoning`, `tokens_total` |
| identity | `model`, `reasoning`, `provider`, `origin`, `plan`, `codex_version` |
| Claude statusline | `cost` |

Collection is not gated by these choices. Changing a list only changes what reaches the 32×8
layout, so a later configuration can use data that was not previously shown.

Runtime settings remain environment variables:

| | Default | |
|---|---|---|
| `AWTRIX_PANEL_CONTEXT_WINDOW` | measured | divisor for the context gauge; set it to override the tier the transcript implies |
| `AWTRIX_PANEL_TTL` | `300` | seconds a session may go quiet before the panel forgets it |
| `AWTRIX_PANEL_INTERVAL` | `1.0` | renderer poll interval |
| `AWTRIX_PANEL_WALK_FPS` | `6` | gait speed while working |
| `AWTRIX_PANEL_LABEL_FPS` | `10` | label animation rate, and the rate the session marks breathe at |
| `AWTRIX_PANEL_LABEL_DWELL` | `18` | frames each metric holds before the next slides in |
| `AWTRIX_PANEL_CONFIG` | `~/.config/awtrix-panel/config.json` | JSON display configuration |
| `AWTRIX_PANEL_HOME` | `~/.local/state/awtrix-panel` | this plugin's state, pidfile and log |
| `PIXELWIRE_HOME` | `~/.local/state/pixelwire` | the display server's state and socket — both halves must agree |

## Optional: quota and an exact context figure

`context_window.used_percentage`, `rate_limits.five_hour` and `cost.total_cost_usd` are handed only
to the **statusline** command, and Claude Code allows one of those. If something already owns it —
`claude-hud`, for instance — a wrapper can feed both: write the JSON to the state file, then pass it
through untouched.

```
/awtrix-panel:setup-quota
```

That reads the current `statusLine.command`, reports what it finds, and — after you confirm —
chains `hooks/statusline-wrapper.sh` in front of it. The wrapper keeps a copy of the JSON for
`hooks/from-statusline.py` and then `exec`s whatever owned the slot, so the HUD is untouched and
our half cannot take it down:

```sh
json=$(cat)
printf '%s' "$json" | "$AWTRIX_PANEL_FILTER" >/dev/null 2>&1 || :
printf '%s' "$json" | exec sh -c "$AWTRIX_PANEL_STATUSLINE"
```

The `|| :` and the trailing `exec` are the point. Our half may fail without consequence, and
nothing of it is left running afterwards.

The statusline payload carries no session id, so the filter keys off the transcript filename —
whose stem is the session id the transcript's own records report. That is how both collectors reach
the same file: the hooks own the status fields, the filter owns `context_pct`, `quota_5h`,
`quota_7d` and `cost_usd`, and neither clobbers the other. The renderer never learns which source
filled a number in, which is what keeps this an add-on rather than a dependency.

It also deliberately does **not** refresh the session's timestamp. A statusline render is not
evidence that a session is live, and touching `updated` on every render would keep a finished one
on the panel forever.

## Troubleshooting

| Symptom | Check |
|---|---|
| nothing on the panel | `pixelwire stat`, then `renderer.log` under this plugin's state directory and `pixelwired.log` under the server's |
| `pixelwired is not installed` | install [pixelwire](https://github.com/webispy/pixelwire) and make sure `pixelwired` is on `PATH` |
| the clock is gone | streaming owns the panel; `pixelwire clear` hands it back at once |
| gauge looks wrong | `AWTRIX_PANEL_CONTEXT_WINDOW` — see above |
| still showing after an agent exits | `SessionEnd` covers an orderly exit; a session that was killed waits out `AWTRIX_PANEL_TTL` |
| panel busy while flashing firmware | `pixelwire stop`, then `pkill -f awtrix-panel/renderer.py` |

The renderer logs every repaint, so the log shows exactly what it decided:

```
18:19:16 starting pixelwired
18:19:17 start pid=89844 poll=1.0s ttl=300s window=auto
18:19:37 paint {'live': 1, 'status': 'busy', 'tokens': 43289, 'context': 22, 'elapsed': 21, 'agents': 0}
18:19:42 paint {'live': 1, 'status': 'permission', 'tokens': 43289, 'context': 22, 'agents': 0}
```

and the server's own log says what reached the panel:

```
18:19:16 pixelwired awtrix-ng on /dev/cu.usbserial-2130 @ 115200, 32x8
18:20:28 pixelwired panel handed back
```
