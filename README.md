# awtrix-claude

Put a Claude Code session on a desk clock: context usage, quota and whether it is working or
waiting for you, on the 32×8 LED matrix of a **Ulanzi TC001**.

Getting there needed a control channel the panel did not have. That part is finished and running:
a fork of [AWTRIX NG](https://github.com/Blueforcer/awtrix-ng) that takes commands and raw frames
over the **USB cable**, so the machine driving the panel and the panel itself do not have to be on
the same network - or on any network at all.

| | Status |
|---|---|
| **Firmware** - serial command channel + 32×8 framebuffer streaming | done, flashed, measured |
| **Display server** - `pixelwire`, one owner of the port, composited layers | done |
| **Claude Code plugin** - session state on the panel | done |

Three repositories side by side in one directory. None of them contains another: the firmware is
rebased on upstream and the display server is released separately, so each is cloned and committed
to on its own.

```
<workspace>/
├── awtrix-claude/   this repository - the plugin, its marketplace, and these notes
├── awtrix-ng/       the firmware fork      webispy/awtrix-ng, branch serial-control
├── pixelwire/       the display server     webispy/pixelwire
└── .venv/           PlatformIO, esptool, mkdocs - only if you are building firmware
```

Paths in these notes are written from the workspace directory, the one holding all three.

| | | |
|---|---|---|
| [`webispy/awtrix-ng`](https://github.com/webispy/awtrix-ng) | branch `serial-control` | takes commands and raw frames over UART0. C++/PlatformIO |
| [`webispy/pixelwire`](https://github.com/webispy/pixelwire) | `main` | owns the port, composites named layers, streams the difference. Rust |
| this one | `main` | the plugin that decides what a Claude Code session looks like. Python, standard library only |

---

## Starting on a machine that has never seen this

The clock keeps its firmware, so a new machine needs neither PlatformIO nor a flash. Three clones,
one build, one plugin install:

```bash
mkdir awtrix && cd awtrix                  # the workspace; call it what you like
git clone https://github.com/webispy/awtrix-claude.git
git clone -b serial-control https://github.com/webispy/awtrix-ng.git
git clone https://github.com/webispy/pixelwire.git

cd pixelwire && ./install.sh && cd ..      # needs Rust 1.88+; puts two binaries in ~/.local/bin
pixelwire stat                             # plug the clock in first - this should find it
```

Then, in Claude Code:

```
/plugin marketplace add /absolute/path/to/awtrix/awtrix-claude
/plugin install awtrix-panel@awtrix-claude
```

Only sessions started **after** that have the hooks, and `plugin install` copies the plugin into a
cache rather than running it from the checkout - so a change here needs a version bump and a
reinstall before it takes effect. [The plugin's own README](plugins/awtrix-panel/README.md) has the
details, the environment variables and the troubleshooting table.

Nothing computes the paths between the three, so the workspace can live anywhere and the
directories can be named anything. Only these notes assume the arrangement above.

**What does not travel.** The flash backup (`tc001-stock-4mb.bin`, gitignored - see
[Recovery](#recovery)) exists only on the machine that made it. Take a copy with you, or read a
fresh one off the unit before you ever flash it again.

---

## Which half do you need?

Two separate toolchains, and most days only the first.

| Goal | What it needs | Set up |
|---|---|---|
| **Run the whole thing** - the plugin on the panel | Rust 1.88+ to build `pixelwire` once, then Python 3 for the plugin. No PlatformIO, no esptool, no `.venv` | [above](#starting-on-a-machine-that-has-never-seen-this) |
| **Talk to the board directly** - a line of text, a setting, is it alive | **uv**, or any Python with `pyserial` | [below](#the-bare-serial-client) |
| **Build or flash firmware** | PlatformIO + esptool + Node.js, in a venv here | [below](#firmware-toolchain) |

The plugin itself needs nothing installed: it is Python standard library throughout, and everything
that touches the serial port lives in `pixelwire`.

The bare serial client is deliberately self-contained too - it declares its own dependencies and
runs from a cache uv manages, so **it never touches `.venv`**. Verified with the environment
scrubbed:

```console
$ env -i HOME=$HOME PATH=$HOME/.local/bin:/usr/bin:/bin awtrix ping
/dev/cu.usbserial-2230  19 ms  ok
```

Nothing below the first row is required to use the clock.

---

## Drive the panel

[`pixelwire`](https://github.com/webispy/pixelwire) is how anything drives the panel now. It holds
the port, composites named layers from any number of clients, streams only what changed, and hands
the panel back to the clock when there is nothing left to show. It also serves a browser console -
the panel as it stands, the layer list, and a drawing board.

```bash
pixelwired --web            # hold the panel and serve http://127.0.0.1:8787
pixelwire stat              # what is on it
pixelwire off               # stop driving it; the clock goes back to its own apps
pixelwire clear             # remove every layer and hand the panel back
```

Its [protocol](https://github.com/webispy/pixelwire/blob/main/docs/protocol.md) is one line of JSON
over a unix socket, and speaking it takes about forty lines in any language.

### The bare serial client

[`awtrix-ng/tools/serialctl/`](https://github.com/webispy/awtrix-ng/tree/serial-control/tools/serialctl)
predates the display server and is kept for talking to the firmware with nothing in between - a
useful thing when the question is whether the *board* is answering. **It opens the port directly, so
it and `pixelwired` cannot both have the panel:** run `pixelwire off` first, or `pixelwire stop`.

Two ways to run it, in order of least setup:

| | Command | Needs |
|---|---|---|
| 1 | `uv run awtrix-ng/tools/serialctl/serialctl.py ping`, from the workspace | **uv only.** It reads the script's [PEP 723](https://peps.python.org/pep-0723/) header and installs `pyserial` into its own cache |
| 2 | `python serialctl.py ping` | any Python that already has `pyserial`. Without it the script stops with a sentence rather than a traceback |

Put it on `PATH` once and it becomes a plain command from any directory:

```bash
ln -s "$PWD/awtrix-ng/tools/serialctl/serialctl.py" ~/.local/bin/awtrix

awtrix ports                                 # what looks like a panel
awtrix ping
awtrix text "Hello" --color FF0000 --hold
awtrix raw cmd/settings '{"brightness":40}'  # any topic the firmware's MQTT layer accepts
awtrix log                                   # watch what the board says
awtrix bench --seconds 10
```

`text` uses the panel's own font, which stops at Cyrillic - anything beyond it renders as `?`.
Anything more than a line of text, and certainly anything Korean, is what the display server is
for: it rasterises here and streams pixels.

`serialctl.py` and `link.py` are the whole client. Copy those two files to whichever machine sits
next to the clock and it works there, with no clone and no toolchain.

---

## Firmware toolchain

Only for building or flashing. Needs [uv](https://docs.astral.sh/uv/) and **Node.js** on `PATH` -
Node is used by one pre-build step (`npx html-minifier-terser`) that regenerates the embedded web
UI, and the build fails without it once `webui/index.html` has changed.

From the workspace directory, beside the three clones:

```bash
uv venv --seed --python 3.13
uv pip install platformio esptool pyyaml -r awtrix-ng/requirements-docs.txt
source .venv/bin/activate
```

> **`--seed` is not optional.** It puts `pip` in the environment, and PlatformIO shells out to
> `python -m pip` when it installs its own packages. Without it, the first ESP32 build dies at
> `tool-esptoolpy` with `No module named pip`, then `MissingPackageManifestError`.

> **`uv tool install platformio` does not work** either, for the same reason: a uv tool environment
> has no `pip`. Use the venv above.

`pyyaml` is for `tools/check_docs_sync.py`, and `requirements-docs.txt` pins mkdocs for
`mkdocs build --strict`. Both are CI gates in that repository.

### Why the workspace and not the fork

Two reasons, both practical. `awtrix-ng/.gitignore` does not cover `.venv`, so an environment
created in there is untracked noise forever. And `pyproject.toml`, `uv.lock`, `.python-version` and
a stub `main.py` at the root of a repository that gets rebased on upstream are permanent merge
noise for files upstream does not have, duplicating the `requirements-docs.txt` already present.

The workspace directory is not a repository at all, so nothing there can become anybody's untracked
noise. Use uv as a `venv` + `pip` replacement, the way this README does: no project files, and the
fork stays as upstream shaped it.

---

## Build and flash

```bash
cd awtrix-ng
pio run -e awtrix                   # ESP32 firmware for the TC001
pio test -e native                  # host unit tests, no hardware
pio run -e native_sim               # simulator, then open localhost:8080
```

Flashing this board is **115200 only**:

```bash
BOOT_APP0=~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin

esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  write-flash -z --flash-mode dio --flash-freq 40m --flash-size 4MB \
    0x1000  .pio/build/awtrix/bootloader.bin \
    0x8000  .pio/build/awtrix/partitions.bin \
    0xe000  "$BOOT_APP0" \
    0x10000 .pio/build/awtrix/firmware.bin
```

The four offsets and the flash flags are what `pio run -t upload` would pass; only the speed
differs. About two minutes: 1.5 MB compresses to ~1.04 MB and the line carries 11.5 KB/s.

> **Do not raise the baud rate.** esptool syncs at 115200 and switches speed *afterwards*, and this
> board's USB bridge does not survive that switch - it fails with `Unable to verify flash chip
> connection` right after `Changing baud rate to …`. At `--baud 115200` the switch is never
> attempted. `--no-stub` does not help: the ESP32 ROM implements the change-baud command itself.

> `pio run -t upload` has no `--project-option` flag, so the 921600 default in `platformio.ini`
> cannot be overridden on the command line. Either edit `upload_speed` or use `esptool` as above.

Stop everything holding the port before flashing - a serial port has one owner, and `esptool`
otherwise fails with `Resource busy`:

```bash
pixelwire stop
pkill -f awtrix-panel/renderer.py
```

The panel beeps for the whole of a USB flash. That is the buzzer on GPIO15, held at its active
level by the pin's internal pull-up while the chip sits in download mode, and no firmware runs
there to pull it low. It is not a fault.

### Prefer OTA after the first flash

`POST /update` writes to the spare app slot from the running firmware, so it needs no download
mode: no beep, and a failed upload leaves the working firmware in place.

```bash
curl -X POST http://<panel-ip>/update -F "firmware=@.pio/build/awtrix/firmware.bin"
```

It is HTTP, so it needs a machine on the panel's network - a phone browser at
**System → Maintenance → Upload firmware** works when your workstation is on a different Wi-Fi.

---

## Recovery

Read the factory firmware off the unit **before** replacing it, and check the size: a short read is
not a backup.

```bash
esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  read-flash 0x0 0x400000 tc001-stock-4mb.bin      # exactly 4,194,304 bytes, ~6.5 min
esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  write-flash 0x0 tc001-stock-4mb.bin              # to go back
```

Backups are not tracked here - 4 MB blobs do not belong in git.

A device that will not boot is always recoverable over USB: download mode is entered by the ROM
bootloader, which no firmware can break, and this board needs no button held.

---

## Measured on this hardware

| | |
|---|---|
| Chip | ESP32-D0WD rev v1.1, 4 MB flash, 40 MHz crystal |
| Serial | `/dev/cu.usbserial-*` - the suffix changes with the physical USB socket |
| Read throughput | 10.8 KB/s at 115200, 94% of theoretical |
| Frame streaming | 13.6 fps of full 24-bit 32×8 frames, no drops |
| Flash write | 101 s for 1.5 MB (1.04 MB after compression) |
| App slot | 1728 KB, 85% full |

## Licence

The firmware fork follows upstream's
[PolyForm Noncommercial](https://github.com/Blueforcer/awtrix-ng/blob/main/LICENSE.md) licence.
Anything in this repository is intended to be usable under the same terms.
