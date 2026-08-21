# Proposal: find sessions through Claude Code's own registry

Status: **proposed, not implemented.** Written 2026-08-20 while the hook-only design was in place.

## The problem

The panel learns that a session exists only when one of the plugin's hooks fires. Hook configuration
is read when a session starts, so a window opened before the plugin was installed reports nothing at
all — the panel shows an empty row while three sessions are plainly working.

Today that cost most of an afternoon. Two of three open sessions had no hooks. The ways out, in the
order they were tried:

| Attempt | Result |
| --- | --- |
| `claude plugin update` | No effect. It compares only the `version` string, so an edited plugin is "already at the latest version". |
| `claude plugin disable` + `enable` from the CLI | Reached one of the two sessions. The watcher subscribes to the in-process settings store, and an external file write is not reliably seen. |
| `/reload-plugins` inside the session | Worked, every time. `Reloaded: … 7 hooks …` — exactly the seven events this plugin registers. |

`/reload-plugins` is the answer for a human who knows to run it. It is not an answer for a plugin
that wants to work the moment it is installed.

## What is available instead

Claude Code maintains its own session registry at `<config>/sessions/<pid>.json`, one file per live
session:

```json
{
  "pid": 9126,
  "sessionId": "d3f63a05-62ae-4c6f-8bdd-609496f181db",
  "cwd": "/Volumes/work/git/ulanzi",
  "status": "busy",
  "statusUpdatedAt": 1787226391707,
  "updatedAt": 1787226391707,
  "name": "ulanzi-58",
  "nameSource": "derived",
  "kind": "interactive",
  "version": "2.1.236",
  "peerProtocol": 1,
  "messagingSocketPath": "/tmp/cc-socks/9126.sock"
}
```

Checked against three live sessions on 2026-08-20: `status` was correct in each (one `busy`, two
`idle`), `statusUpdatedAt` tracked within seconds, every `pid` was alive, and there were no stale
files left by closed sessions.

What this gives that hooks cannot:

- **Which sessions exist, and which are busy — with no hooks at all.** The whole
  reload-before-it-works problem disappears.
- **A name per session** (`ulanzi-58`, `pass-workspace-3e`), which is something a 32×8 panel could
  actually use to say *which* window it is describing.

What it does not carry, and what therefore still needs the hooks and the statusline filter:

- context percentage, 5-hour and 7-day quota, running cost
- blocked-on-permission and failure states
- subagent counts
- `busy_since`, and so the elapsed-time readout

## Design

Two sources, each for what it is good at:

- **The registry decides which sessions exist and whether each is busy.** It drives the row of marks
  along the bottom.
- **The hook and statusline files supply the numbers.** They drive the two gauges and the cycling
  label. Match a hook file to a registry entry on `sessionId`.

A session with a registry entry and no hook file still gets a mark; it just has no numbers of its
own. That is the case this proposal exists for.

### Resolving the config directory

`~/.claude-enter` is one user's setting, not a path to hard-code. Claude Code's own rule is
`process.env.CLAUDE_CONFIG_DIR` when set, otherwise the home directory — but reading the wrong
directory does not fail, it reports zero sessions, which is the quiet kind of wrong that cost the
most time today. So resolve it in order and *verify* each candidate:

1. `CLAUDE_CONFIG_DIR` from the environment. Confirmed present in the Claude Code process and
   inherited by child processes, so hooks and the renderer both see it.
2. Otherwise, derive it from a transcript path the session files already store. These are laid out
   as `<config>/projects/<slug>/<id>.jsonl`, so three `dirname` calls give the config directory —
   Claude Code's own answer rather than a guess, and it works even where the variable is not
   inherited.
3. Otherwise `~/.claude`.

Accept a candidate only if `<candidate>/sessions` exists. On this machine both `~/.claude-enter/
sessions` and `~/.claude/sessions` exist and the second is empty, so a candidate that merely looks
plausible is not good enough.

Collect candidates as a set rather than picking one: the renderer is a long-lived process that
inherited one environment, and someone running sessions under two different config directories would
otherwise have half of them invisible.

### Falling back

The registry is not a documented interface. It has version markers (`version`, `peerProtocol`) but
no promise. So: read it when it is there and shaped as expected, and drop silently back to the
hook-only behaviour when it is not. Never let a missing or changed registry take the panel down —
worth a line in the log, nothing more.

## What a SessionEnd hook already fixes

Registering `SessionEnd` and deleting the session file covers the ordinary case: a window closed with
`/quit` leaves the row of marks within the second instead of after the five-minute TTL. That landed
separately and does not depend on this proposal.

It cannot cover a session that dies without running a hook - killed, crashed, or a terminal closed
out from under it. The TTL is the backstop there, and it is a five-minute one. Cross-checking the
registry would close the gap properly, because Claude Code removes a session's registry file as soon
as the session goes: measured on 2026-08-20, a session quit with `/quit` had its `<pid>.json` gone
immediately while the plugin's own file sat for the full TTL.

## Risks

- **Undocumented format.** Mitigated by the fallback above, and by treating every field as optional.
- **Two sources of truth for status.** The registry says `busy`/`idle`; the hooks additionally know
  `permission` and `error`, which the registry cannot express. The hook status has to win where it
  exists, or a session blocked on a permission prompt would be drawn as merely busy.
- **Sessions that are not interactive.** `kind` is `"interactive"` for a terminal session; other
  kinds should be checked before being counted, or the panel may start describing something that is
  not a window anyone is sitting at.

## Open questions

- **Focus.** Which session is actually in front is still unknown. Claude Code tracks it — ANSI focus
  reporting, `CSI ?1004h`, kept in an in-process `userPresence` store — but does not publish it, and
  its own fallback when a terminal does not report focus is "most recently interacted", which is the
  heuristic the panel already uses. An external route exists on this machine (iTerm2 exposes the
  frontmost tab's tty over AppleScript, and each session has its own tty) but it needs macOS
  automation consent, is terminal-specific, and has to be polled. Deferred.
- **Phase.** All the marks share one layer and therefore one animation clock, so busy sessions
  breathe in lockstep. Splitting them into a layer each would let each session breathe on its own
  schedule. Unclear which reads better; wants looking at rather than deciding.
- **Panel brightness** was changed from 60 to 70 during testing and the original was not recorded.
